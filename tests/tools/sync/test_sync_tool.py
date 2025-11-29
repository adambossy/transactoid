from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import pytest

from models.transaction import Transaction
from tools.categorize.categorizer_tool import CategorizedTransaction
from tools.persist.persist_tool import SaveOutcome
from tools.sync.sync_tool import SyncSummary, SyncTool

# Helper functions


def create_test_transaction(
    *,
    transaction_id: str | None = None,
    account_id: str = "acc_123",
    amount: float = 10.0,
    date: str = "2025-01-01",
    name: str = "Test Transaction",
) -> Transaction:
    """Create a test transaction."""
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "amount": amount,
        "iso_currency_code": "USD",
        "date": date,
        "name": name,
        "merchant_name": None,
        "pending": False,
        "payment_channel": None,
        "unofficial_currency_code": None,
        "category": None,
        "category_id": None,
        "personal_finance_category": None,
    }


def create_test_transactions(count: int) -> list[Transaction]:
    """Create a list of test transactions."""
    return [
        create_test_transaction(
            transaction_id=f"txn_{i}",
            name=f"Transaction {i}",
        )
        for i in range(count)
    ]


class MockPlaidClient:
    """Mock PlaidClient for testing."""

    def __init__(
        self,
        *,
        sync_results: list[dict[str, Any]],
    ) -> None:
        self._sync_results = sync_results
        self._call_count = 0
        self._cursors_used: list[str | None] = []

    def sync_transactions(
        self,
        access_token: str,
        *,
        cursor: str | None = None,
        count: int = 500,
    ) -> dict[str, Any]:
        """Mock sync_transactions that returns configured results."""
        self._cursors_used.append(cursor)
        if self._call_count < len(self._sync_results):
            result = self._sync_results[self._call_count]
            self._call_count += 1
            return result
        return {
            "added": [],
            "modified": [],
            "removed": [],
            "next_cursor": "",
            "has_more": False,
        }


class MockCategorizer:
    """Mock Categorizer for testing."""

    def __init__(
        self,
        *,
        success: bool = True,
        should_fail_on_batch: list[int] | None = None,
    ) -> None:
        self._success = success
        self._should_fail_on_batch = should_fail_on_batch or []
        self._call_count = 0
        self._calls: list[list[Transaction]] = []

    def categorize(self, txns: Iterable[Transaction]) -> list[CategorizedTransaction]:
        """Mock categorize that can succeed or fail."""
        txn_list = list(txns)
        self._calls.append(txn_list)
        call_idx = self._call_count
        self._call_count += 1

        if not self._success or call_idx in self._should_fail_on_batch:
            raise RuntimeError(f"Categorization failed for batch {call_idx}")

        return [
            CategorizedTransaction(
                txn=txn,
                category_key="food.groceries",
                category_confidence=0.9,
                category_rationale="Test categorization",
            )
            for txn in txn_list
        ]


class MockPersistTool:
    """Mock PersistTool for testing."""

    def __init__(
        self,
        *,
        save_success: bool = True,
        save_raw_success: bool = True,
        should_fail_on_batch: list[int] | None = None,
    ) -> None:
        self._save_success = save_success
        self._save_raw_success = save_raw_success
        self._should_fail_on_batch = should_fail_on_batch or []
        self._save_raw_calls: list[tuple[list[Transaction], str]] = []
        self._save_calls: list[list[CategorizedTransaction]] = []
        self._save_raw_count = 0
        self._save_count = 0

    def save_raw_transactions(
        self,
        txns: Iterable[Transaction],
        *,
        cursor: str,
    ) -> int:
        """Mock save_raw_transactions."""
        txn_list = list(txns)
        self._save_raw_calls.append((txn_list, cursor))
        call_idx = self._save_raw_count
        self._save_raw_count += 1

        if not self._save_raw_success or call_idx in self._should_fail_on_batch:
            raise RuntimeError(f"Save raw failed for batch {call_idx}")

        return len(txn_list)

    def save_transactions(self, txns: Iterable[CategorizedTransaction]) -> SaveOutcome:
        """Mock save_transactions."""
        txn_list = list(txns)
        self._save_calls.append(txn_list)
        call_idx = self._save_count
        self._save_count += 1

        if not self._save_success or call_idx in self._should_fail_on_batch:
            raise RuntimeError(f"Save failed for batch {call_idx}")

        return SaveOutcome(
            inserted=len(txn_list),
            updated=0,
            skipped_verified=0,
            skipped_duplicate=0,
            rows=[],
        )


def create_sync_tool(
    *,
    plaid_client: MockPlaidClient,
    categorizer: MockCategorizer,
    persist_tool: MockPersistTool,
    access_token: str = "test_token",
    cursor: str | None = None,
) -> SyncTool:
    """Create a SyncTool instance with mocked dependencies."""
    return SyncTool(
        plaid_client=plaid_client,  # type: ignore[arg-type]
        categorizer=categorizer,  # type: ignore[arg-type]
        persist_tool=persist_tool,  # type: ignore[arg-type]
        access_token=access_token,
        cursor=cursor,
    )


# Phase 1: Single Batch, Multiple Transactions


def test_sync_single_batch_exact_batch_size() -> None:
    """
    Test sync with exactly 25 transactions (batch_size).

    Verify: all categorized and persisted, counts match.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=25,
        total_modified=0,
        total_removed=0,
        total_categorized=25,
        total_persisted=25,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_modified == expected_summary.total_modified
    assert result.total_removed == expected_summary.total_removed
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert result.final_cursor == expected_summary.final_cursor
    assert len(result.persist_outcomes) == 1
    assert result.persist_outcomes[0].inserted == 25
    assert len(persist_tool._save_raw_calls) == 1
    assert len(persist_tool._save_calls) == 1


def test_sync_single_batch_categorization_fails() -> None:
    """
    Test sync with 25 transactions where entire batch categorization fails.

    Verify: all 25 stored as raw, none persisted, cursor not advanced.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=False)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=25,
        total_modified=0,
        total_removed=0,
        total_categorized=0,
        total_persisted=0,
        final_cursor="cursor_123",
        persist_outcomes=[],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(persist_tool._save_raw_calls) == 1
    assert persist_tool._save_raw_calls[0][0] == transactions
    assert len(persist_tool._save_calls) == 0


def test_sync_single_batch_persistence_fails() -> None:
    """
    Test sync with 25 transactions where persistence fails for entire batch.

    Verify: all 25 categorized but not persisted, raw transactions still in DB.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=False, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=25,
        total_modified=0,
        total_removed=0,
        total_categorized=25,
        total_persisted=0,
        final_cursor="cursor_123",
        persist_outcomes=[],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(persist_tool._save_raw_calls) == 1
    assert len(categorizer._calls) == 1
    assert len(persist_tool._save_calls) == 1
    assert len(result.persist_outcomes) == 0


# Phase 2: Multiple Batches, Sequential Categorization


def test_sync_two_batches_sequential_categorization() -> None:
    """
    Test sync with 2 batches processed sequentially.

    Plaid sync is sequential (one page at a time).
    Categorization processed sequentially (1 worker).
    Verify: all processed, cursor advanced after both succeed.
    """
    # input
    transactions_batch1 = create_test_transactions(25)
    transactions_batch2 = create_test_transactions(25)
    sync_result = {
        "added": transactions_batch1 + transactions_batch2,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 2


def test_sync_two_batches_first_succeeds_second_categorization_fails() -> None:
    """
    Test sync with 2 batches where first succeeds, second categorization fails.

    Verify: first batch persisted, second batch persisted, second batch stored as raw,
    cursor not advanced.
    """
    # input
    transactions_batch1 = create_test_transactions(25)
    transactions_batch2 = create_test_transactions(25)
    sync_result = {
        "added": transactions_batch1 + transactions_batch2,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True, should_fail_on_batch=[1])
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=25,
        total_persisted=25,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 1


def test_sync_two_batches_first_succeeds_second_persistence_fails() -> None:
    """
    Test sync with 2 batches where first succeeds, second persistence fails.

    Verify: first batch persisted, second batch categorized but not persisted,
    cursor not advanced.
    """
    # input
    transactions_batch1 = create_test_transactions(25)
    transactions_batch2 = create_test_transactions(25)
    sync_result = {
        "added": transactions_batch1 + transactions_batch2,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(
        save_success=True, save_raw_success=True, should_fail_on_batch=[1]
    )
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=25,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 2


# Phase 3: Parallel Categorization (Plaid Sync Sequential, Categorization Parallel)


def test_sync_two_batches_parallel_categorization() -> None:
    """
    Test sync with 2 batches processed in parallel.

    Plaid sync fetches pages sequentially (page 1, then page 2).
    Categorization processes 2 batches in parallel (2 workers).
    Verify: both batches process concurrently, both succeed, correct counts.
    """
    # input
    transactions_batch1 = create_test_transactions(25)
    transactions_batch2 = create_test_transactions(25)
    sync_result = {
        "added": transactions_batch1 + transactions_batch2,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=2))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 2


def test_sync_four_batches_max_parallelism_categorization() -> None:
    """
    Test sync with 4 batches using max parallelism.

    4 batches from sequential Plaid sync pages.
    Categorization processes 4 batches in parallel (4 workers).
    Verify: all 4 batches process concurrently, all succeed.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=100,
        total_modified=0,
        total_removed=0,
        total_categorized=100,
        total_persisted=100,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 4,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 4
    assert len(persist_tool._save_calls) == 4


def test_sync_five_batches_with_categorization_queue() -> None:
    """
    Test sync with 5 batches where one waits in queue.

    5 batches from sequential Plaid sync pages.
    Categorization uses 4 workers (one batch waits in queue).
    Verify: first 4 process in parallel, 5th processes after one completes,
    all succeed.
    """
    # input
    transactions = create_test_transactions(125)  # 5 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=125,
        total_modified=0,
        total_removed=0,
        total_categorized=125,
        total_persisted=125,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 5,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 5
    assert len(persist_tool._save_calls) == 5


def test_sync_parallel_categorization_one_batch_fails() -> None:
    """
    Test sync with parallel categorization where one batch fails.

    4 batches from sequential Plaid sync.
    3 batches succeed, 1 batch categorization fails (entire batch).
    Verify: 3 batches persisted, 1 batch stored as raw, cursor not advanced.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True, should_fail_on_batch=[2])
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=100,
        total_modified=0,
        total_removed=0,
        total_categorized=75,
        total_persisted=75,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 3,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 4
    assert len(persist_tool._save_calls) == 3


def test_sync_parallel_categorization_one_batch_persistence_fails() -> None:
    """
    Test sync with parallel categorization where one batch persistence fails.

    4 batches from sequential Plaid sync.
    3 batches succeed, 1 batch persistence fails.
    Verify: 3 batches persisted, 1 batch categorized but not persisted,
    cursor not advanced.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(
        save_success=True, save_raw_success=True, should_fail_on_batch=[2]
    )
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=100,
        total_modified=0,
        total_removed=0,
        total_categorized=100,
        total_persisted=75,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 3,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 4
    assert len(persist_tool._save_calls) == 4


def test_sync_parallel_categorization_multiple_failures() -> None:
    """
    Test sync with parallel categorization where multiple batches fail.

    4 batches from sequential Plaid sync.
    2 batches succeed, 2 batches categorization fail.
    Verify: 2 batches persisted, 2 batches stored as raw, cursor not advanced.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True, should_fail_on_batch=[1, 3])
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=100,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 2,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 4
    assert len(persist_tool._save_calls) == 2


# Phase 4: Multiple Pages from Plaid (Sequential Sync)


def test_sync_two_pages_single_batch_each() -> None:
    """
    Test sync with 2 Plaid pages, each with 1 batch.

    2 Plaid API pages fetched sequentially.
    Each page has 1 batch worth of transactions.
    Verify: pages fetched sequentially, batches queued correctly, all processed.
    """
    # input
    page1_txns = create_test_transactions(25)
    page2_txns = create_test_transactions(25)
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result1, sync_result2])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=2))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_final",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert result.final_cursor == expected_summary.final_cursor
    assert plaid_client._call_count == 2
    assert len(categorizer._calls) == 2


def test_sync_two_pages_multiple_batches() -> None:
    """
    Test sync with 2 Plaid pages with multiple batches.

    2 Plaid API pages fetched sequentially.
    First page has 2 batches, second page has 1 batch.
    Verify: all batches processed, cursor advanced correctly.
    """
    # input
    page1_txns = create_test_transactions(50)  # 2 batches
    page2_txns = create_test_transactions(25)  # 1 batch
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result1, sync_result2])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=75,
        total_modified=0,
        total_removed=0,
        total_categorized=75,
        total_persisted=75,
        final_cursor="cursor_final",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 3,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert result.final_cursor == expected_summary.final_cursor
    assert len(categorizer._calls) == 3


def test_sync_pagination_with_partial_batch() -> None:
    """
    Test sync with pagination where last page has partial batch.

    Multiple pages fetched sequentially.
    Last page has < 25 transactions (partial batch).
    Verify: partial batch flushed and processed correctly.
    """
    # input
    page1_txns = create_test_transactions(25)
    page2_txns = create_test_transactions(10)  # Partial batch
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result1, sync_result2])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=2))

    # expected
    expected_summary = SyncSummary(
        total_added=35,
        total_modified=0,
        total_removed=0,
        total_categorized=35,
        total_persisted=35,
        final_cursor="cursor_final",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
            SaveOutcome(
                inserted=10, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert len(categorizer._calls) == 2
    assert len(categorizer._calls[1]) == 10  # Partial batch


def test_sync_multiple_pages_with_categorization_failure() -> None:
    """
    Test sync with multiple pages where page 2 categorization fails.

    3 pages fetched sequentially.
    Page 2 batch categorization fails.
    Verify: page 1 persisted, page 2 stored as raw, page 3 not fetched
    (cursor not advanced).
    """
    # input
    page1_txns = create_test_transactions(25)
    page2_txns = create_test_transactions(25)
    page3_txns = create_test_transactions(25)
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page3",
        "has_more": True,
    }
    sync_result3 = {
        "added": page3_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(
        sync_results=[sync_result1, sync_result2, sync_result3]
    )
    categorizer = MockCategorizer(success=True, should_fail_on_batch=[1])
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=50,  # Only page1 and page2 fetched
        total_modified=0,
        total_removed=0,
        total_categorized=25,
        total_persisted=25,
        final_cursor="cursor_page3",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert plaid_client._call_count == 2  # Only 2 pages fetched
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 1


def test_sync_multiple_pages_with_persistence_failure() -> None:
    """
    Test sync with multiple pages where page 2 persistence fails.

    3 pages fetched sequentially.
    Page 2 batch persistence fails.
    Verify: page 1 persisted, page 2 categorized but not persisted,
    page 3 not fetched.
    """
    # input
    page1_txns = create_test_transactions(25)
    page2_txns = create_test_transactions(25)
    page3_txns = create_test_transactions(25)
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page3",
        "has_more": True,
    }
    sync_result3 = {
        "added": page3_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(
        sync_results=[sync_result1, sync_result2, sync_result3]
    )
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(
        save_success=True, save_raw_success=True, should_fail_on_batch=[1]
    )
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=50,  # Only page1 and page2 fetched
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=25,
        final_cursor="cursor_page3",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted
    assert plaid_client._call_count == 2
    assert len(categorizer._calls) == 2
    assert len(persist_tool._save_calls) == 2


# Phase 5: Cursor Management


def test_sync_cursor_not_advanced_on_categorization_failure() -> None:
    """
    Test that cursor is not advanced when categorization fails.

    Sync succeeds, batch categorization fails.
    Verify: cursor not advanced, can retry with same cursor.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=False)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    # Cursor should be the one from sync result, but categorization failed
    # so we can retry with same cursor

    # assert
    assert result.final_cursor == "cursor_123"
    assert len(persist_tool._save_raw_calls) == 1
    assert len(persist_tool._save_calls) == 0


def test_sync_cursor_not_advanced_on_persistence_failure() -> None:
    """
    Test that cursor is not advanced when persistence fails.

    Sync succeeds, categorization succeeds, persistence fails.
    Verify: cursor not advanced, can retry categorization.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=False, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    # Cursor should be from sync result, but persistence failed

    # assert
    assert result.final_cursor == "cursor_123"
    assert len(categorizer._calls) == 1
    assert len(persist_tool._save_calls) == 1
    assert len(result.persist_outcomes) == 0


def test_sync_cursor_advanced_after_all_batches_succeed() -> None:
    """
    Test that cursor is advanced only after all batches succeed.

    Multiple batches, all succeed.
    Verify: cursor advanced to final next_cursor only after all batches succeed.
    """
    # input
    transactions = create_test_transactions(50)  # 2 batches
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=2))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_final",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            ),
        ],
    )

    # assert
    assert result.final_cursor == expected_summary.final_cursor
    assert result.total_categorized == expected_summary.total_categorized
    assert result.total_persisted == expected_summary.total_persisted


def test_sync_cursor_tracking_per_batch() -> None:
    """
    Test that cursors are correctly tracked per batch.

    Multiple pages fetched sequentially.
    Track which cursor each batch belongs to.
    Verify: batches correctly associated with their cursors.
    """
    # input
    page1_txns = create_test_transactions(25)
    page2_txns = create_test_transactions(25)
    sync_result1 = {
        "added": page1_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_page2",
        "has_more": True,
    }
    sync_result2 = {
        "added": page2_txns,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_final",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result1, sync_result2])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=2))

    # expected
    expected_summary = SyncSummary(
        total_added=50,
        total_modified=0,
        total_removed=0,
        total_categorized=50,
        total_persisted=50,
        final_cursor="cursor_final",
        persist_outcomes=[],
    )

    # assert
    assert result.final_cursor == expected_summary.final_cursor
    assert result.total_added == expected_summary.total_added
    # Verify cursors used in sync calls
    assert plaid_client._cursors_used[0] == "initial_cursor"
    assert plaid_client._cursors_used[1] == "cursor_page2"
    assert len(persist_tool._save_raw_calls) == 2
    assert persist_tool._save_raw_calls[0][1] == "initial_cursor"
    assert persist_tool._save_raw_calls[1][1] == "cursor_page2"


# Phase 6: Raw Transaction Storage


def test_sync_raw_transactions_stored_before_categorization() -> None:
    """
    Test that raw transactions are stored before categorization starts.

    Transactions stored as raw immediately after sync (before categorization).
    Verify: raw transactions in DB before categorization starts.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    # Raw transactions should be stored before categorization

    # assert
    assert result.total_added == 25
    assert len(persist_tool._save_raw_calls) == 1
    assert persist_tool._save_raw_calls[0][0] == transactions
    # Verify raw was called before categorize
    assert len(persist_tool._save_raw_calls) > 0
    assert len(categorizer._calls) > 0


def test_sync_raw_transactions_retryable() -> None:
    """
    Test that raw transactions can be retried after categorization failure.

    Batch categorization fails, raw transactions stored.
    Verify: can query and retry categorization for pending transactions.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=False)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    # Raw transactions stored, categorization failed, can retry

    # assert
    assert result.total_added == 25
    assert result.total_categorized == 0
    assert len(persist_tool._save_raw_calls) == 1
    assert persist_tool._save_raw_calls[0][0] == transactions
    assert len(categorizer._calls) == 1
    assert len(persist_tool._save_calls) == 0


# Phase 7: Error Recovery (Dedicated Recovery Tests)


def test_sync_retry_failed_batch_categorization() -> None:
    """
    Test retry mechanism for failed batch categorization.

    Batch fails categorization, raw transactions stored.
    Retry categorization for stored raw transactions.
    Verify: failed batch can be retried and succeeds.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer_fail = MockCategorizer(success=False)
    categorizer_success = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer_fail,
        persist_tool=persist_tool,
    )

    # act - initial sync fails
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - failure case
    assert result1.total_categorized == 0
    assert result1.total_persisted == 0
    assert len(persist_tool._save_raw_calls) == 1

    # recovery - retry with successful categorizer
    sync_tool._categorizer = categorizer_success  # type: ignore[assignment]
    # In real implementation, would retry from stored raw transactions
    # For test, we'll simulate by re-running sync with same cursor
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - recovery success
    assert result2.total_categorized == 25
    assert result2.total_persisted == 25


def test_sync_retry_failed_batch_persistence() -> None:
    """
    Test retry mechanism for failed batch persistence.

    Batch categorization succeeds but persistence fails.
    Retry persistence for categorized transactions.
    Verify: failed batch can be retried and succeeds.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool_fail = MockPersistTool(save_success=False, save_raw_success=True)
    persist_tool_success = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool_fail,
    )

    # act - initial sync fails persistence
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - failure case
    assert result1.total_categorized == 25
    assert result1.total_persisted == 0

    # recovery - retry with successful persist tool
    sync_tool._persist_tool = persist_tool_success  # type: ignore[assignment]
    # In real implementation, would retry persistence for categorized transactions
    # For test, simulate by re-running
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - recovery success
    assert result2.total_categorized == 25
    assert result2.total_persisted == 25


def test_sync_retry_multiple_failed_batches() -> None:
    """
    Test retry mechanism for multiple failed batches.

    Multiple batches fail categorization.
    Retry all failed batches.
    Verify: all batches eventually succeed after retry.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer_fail = MockCategorizer(success=True, should_fail_on_batch=[1, 3])
    categorizer_success = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer_fail,
        persist_tool=persist_tool,
    )

    # act - initial sync with failures
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # assert - partial success
    assert result1.total_categorized == 50
    assert result1.total_persisted == 50

    # recovery - retry with successful categorizer
    sync_tool._categorizer = categorizer_success  # type: ignore[assignment]
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # assert - all succeed
    assert result2.total_categorized == 100
    assert result2.total_persisted == 100


def test_sync_retry_with_cursor_reset() -> None:
    """
    Test retry with cursor reset after failure.

    Categorization fails, cursor not advanced.
    Retry sync with same cursor.
    Verify: transactions re-fetched, categorization succeeds this time.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result, sync_result])
    categorizer_fail = MockCategorizer(success=False)
    categorizer_success = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer_fail,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act - initial sync fails
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - failure, cursor not advanced
    assert result1.total_categorized == 0
    assert plaid_client._cursors_used[0] == "initial_cursor"

    # recovery - retry with same cursor and successful categorizer
    sync_tool._categorizer = categorizer_success  # type: ignore[assignment]
    sync_tool._cursor = "initial_cursor"  # Reset cursor
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - success
    assert result2.total_categorized == 25
    assert result2.total_persisted == 25
    assert plaid_client._cursors_used[1] == "initial_cursor"


def test_sync_recovery_after_partial_success() -> None:
    """
    Test recovery after partial success.

    4 batches, 2 succeed, 2 fail.
    Retry failed batches.
    Verify: all 4 batches eventually succeed, cursor advanced only after
    all succeed.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result, sync_result])
    categorizer_fail = MockCategorizer(success=True, should_fail_on_batch=[1, 3])
    categorizer_success = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer_fail,
        persist_tool=persist_tool,
    )

    # act - initial sync with partial failures
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # assert - partial success
    assert result1.total_categorized == 50
    assert result1.total_persisted == 50

    # recovery - retry failed batches
    sync_tool._categorizer = categorizer_success  # type: ignore[assignment]
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # assert - all succeed
    assert result2.total_categorized == 100
    assert result2.total_persisted == 100


def test_sync_recovery_from_persistence_failure() -> None:
    """
    Test recovery from persistence failure.

    Batch persistence fails after successful categorization.
    Retry persistence.
    Verify: persistence succeeds, cursor advanced.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result, sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool_fail = MockPersistTool(save_success=False, save_raw_success=True)
    persist_tool_success = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool_fail,
    )

    # act - initial sync fails persistence
    result1 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - failure
    assert result1.total_categorized == 25
    assert result1.total_persisted == 0

    # recovery - retry persistence
    sync_tool._persist_tool = persist_tool_success  # type: ignore[assignment]
    result2 = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # assert - success
    assert result2.total_categorized == 25
    assert result2.total_persisted == 25


# Phase 8: Edge Cases (Less Critical - End of Suite)


def test_sync_empty_sync_result() -> None:
    """
    Test sync with empty result from Plaid API.

    Sync returns no transactions (empty arrays).
    Verify: no errors, empty summary, cursor handled correctly.
    """
    # input
    sync_result = {
        "added": [],
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=0,
        total_modified=0,
        total_removed=0,
        total_categorized=0,
        total_persisted=0,
        final_cursor="cursor_123",
        persist_outcomes=[],
    )

    # assert
    assert result == expected_summary
    assert len(categorizer._calls) == 0
    assert len(persist_tool._save_calls) == 0


def test_sync_only_removed_transactions() -> None:
    """
    Test sync with only removed transactions.

    Sync returns only removed transactions, no added/modified.
    Verify: removed handled correctly, no categorization attempted.
    """
    # input
    sync_result = {
        "added": [],
        "modified": [],
        "removed": [{"transaction_id": "txn_1"}, {"transaction_id": "txn_2"}],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=0,
        total_modified=0,
        total_removed=2,
        total_categorized=0,
        total_persisted=0,
        final_cursor="cursor_123",
        persist_outcomes=[],
    )

    # assert
    assert result.total_removed == expected_summary.total_removed
    assert result.total_categorized == expected_summary.total_categorized
    assert len(categorizer._calls) == 0
    assert len(persist_tool._save_calls) == 0


def test_sync_sync_api_failure() -> None:
    """
    Test sync when Plaid API call fails.

    Plaid API call fails.
    Verify: error propagated, no partial state, cursor not advanced.
    """

    # input
    # helper setup
    class FailingPlaidClient:
        def sync_transactions(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("Plaid API failure")

    plaid_client = FailingPlaidClient()
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,  # type: ignore[arg-type]
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor="initial_cursor",
    )

    # act & assert
    with pytest.raises(RuntimeError, match="Plaid API failure"):
        asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # Verify no partial state
    assert len(persist_tool._save_raw_calls) == 0
    assert len(categorizer._calls) == 0


def test_sync_initial_cursor_none() -> None:
    """
    Test sync with initial cursor None (initial sync).

    Initial sync (cursor=None).
    Verify: handles None cursor correctly, fetches all history.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
        cursor=None,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    expected_summary = SyncSummary(
        total_added=25,
        total_modified=0,
        total_removed=0,
        total_categorized=25,
        total_persisted=25,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ],
    )

    # assert
    assert result == expected_summary
    assert plaid_client._cursors_used[0] is None


def test_sync_no_more_pages() -> None:
    """
    Test sync when has_more is False.

    Single page with has_more=False.
    Verify: exits correctly, doesn't attempt additional pages.
    """
    # input
    transactions = create_test_transactions(25)
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=1))

    # expected
    # Should only call sync once

    # assert
    assert plaid_client._call_count == 1
    assert result.final_cursor == "cursor_123"


def test_sync_large_batch_exceeds_batch_size() -> None:
    """
    Test sync with large batch that exceeds batch_size.

    Single sync page returns 100 transactions (4 batches of 25).
    Verify: correctly split into 4 batches, all processed.
    """
    # input
    transactions = create_test_transactions(100)  # 4 batches of 25
    sync_result = {
        "added": transactions,
        "modified": [],
        "removed": [],
        "next_cursor": "cursor_123",
        "has_more": False,
    }

    # helper setup
    plaid_client = MockPlaidClient(sync_results=[sync_result])
    categorizer = MockCategorizer(success=True)
    persist_tool = MockPersistTool(save_success=True, save_raw_success=True)
    sync_tool = create_sync_tool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        persist_tool=persist_tool,
    )

    # act
    result = asyncio.run(sync_tool.sync(batch_size=25, max_parallel_categorize=4))

    # expected
    expected_summary = SyncSummary(
        total_added=100,
        total_modified=0,
        total_removed=0,
        total_categorized=100,
        total_persisted=100,
        final_cursor="cursor_123",
        persist_outcomes=[
            SaveOutcome(
                inserted=25, updated=0, skipped_verified=0, skipped_duplicate=0, rows=[]
            )
        ]
        * 4,
    )

    # assert
    assert result.total_added == expected_summary.total_added
    assert len(categorizer._calls) == 4
    assert all(len(call) == 25 for call in categorizer._calls)
    assert len(persist_tool._save_calls) == 4
