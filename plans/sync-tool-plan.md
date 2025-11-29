# Sync Tool Planning Document

## Current State

### Existing Implementation
The `SyncTool` class exists at `tools/sync/sync_tool.py` with a basic structure:

```12:68:tools/sync/sync_tool.py
class SyncTool:
    """
    Sync tool that calls Plaid's transaction sync API and categorizes all
    results using an LLM.
    """

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        *,
        access_token: str,
        cursor: str | None = None,
    ) -> None:
        """
        Initialize the sync tool.

        Args:
            plaid_client: Plaid client instance
            categorizer: Categorizer instance for LLM-based categorization
            access_token: Plaid access token for the item
            cursor: Optional cursor for incremental sync (None for initial sync)
        """
        self._plaid_client = plaid_client
        self._categorizer = categorizer
        self._access_token = access_token
        self._cursor = cursor

    def sync(
        self,
        *,
        count: int = 500,
    ) -> tuple[list[CategorizedTransaction], str]:
        """
        Sync transactions from Plaid and categorize them.

        Args:
            count: Maximum number of transactions to fetch per request

        Returns:
            Tuple of (categorized_transactions, next_cursor)
        """
        # Call Plaid's sync_transactions API
        sync_result = self._plaid_client.sync_transactions(
            self._access_token,
            cursor=self._cursor,
            count=count,
        )

        # Extract transactions from sync result
        added: list[Transaction] = sync_result.get("added", [])
        modified: list[Transaction] = sync_result.get("modified", [])
        next_cursor = sync_result.get("next_cursor", "")

        # Combine added and modified transactions
        all_txns = added + modified

        # Categorize all transactions using LLM
        categorized_txns = self._categorizer.categorize(all_txns)

        return categorized_txns, next_cursor
```

### What's Working
- ✅ Basic structure and interface defined
- ✅ Integration with `PlaidClient.sync_transactions()` 
- ✅ Returns categorized transactions and next cursor
- ✅ Handles both `added` and `modified` transactions

### What's Missing or Needs Clarification

#### 1. **Removed Transactions Handling**
   - **Current**: The sync result includes `removed` transactions, but they're not processed
   - **Question**: How should removed transactions be handled?
     - Option A: Return them separately for caller to handle
     - Option B: Mark them as deleted in the database (requires DB integration)
     - Option C: Ignore them (not recommended - data integrity issue)
   - **Recommendation**: Return removed transactions separately in the result, let `PersistTool` handle deletion logic

#### 2. **Cursor Management**
   - **Current**: Cursor is passed in constructor and returned from `sync()`
   - **Question**: How should cursors be persisted between syncs?
     - Option A: Store in database (requires `items` or `sync_state` table)
     - Option B: Return to caller, caller manages persistence
     - Option C: Store in file system (less ideal)
   - **Current State**: No database table for storing cursors/items
   - **Recommendation**: For now, return cursor to caller. Future: add `items` table with `access_token`, `cursor`, `institution_name`, `last_synced_at`

#### 3. **Cursor Update After Sync**
   - **Current**: `sync()` returns `next_cursor` but doesn't update `self._cursor`
   - **Question**: Should `SyncTool` update its internal cursor state?
   - **Recommendation**: Add a method to update cursor, or make `sync()` update `self._cursor` automatically

#### 4. **Error Handling**
   - **Current**: No explicit error handling
   - **Needs**: 
     - Handle Plaid API errors (network, auth, rate limits)
     - Handle categorization failures (partial failures?)
     - Handle invalid access tokens

#### 5. **Pagination/Iteration**
   - **Current**: Single sync call with `count` limit
   - **Question**: Should `SyncTool` handle pagination automatically?
   - **Plaid Behavior**: If `has_more` is true, caller should call again with `next_cursor`
   - **Recommendation**: Keep single-page sync, add helper method `sync_all()` that loops until complete

#### 6. **Integration Points**

   **a. With `scripts/run.py`**
   ```python
   def run_sync(
       *,
       access_token: str,
       cursor: Optional[str] = None,
       count: int = 500,
   ) -> None:
   ```
   - **Status**: Stub implementation
   - **Needs**: 
     - Initialize `PlaidClient`, `Categorizer`, `SyncTool`
     - Call `sync()` and handle results
     - Optionally persist via `PersistTool`
     - Print summary/logging

   **b. With `ui/cli.py`**
   ```python
   @app.command("sync")
   def sync(access_token: str, cursor: str | None = None, count: int = 500) -> None:
   ```
   - **Status**: Stub implementation
   - **Needs**: Call `run_sync()` from scripts

   **c. With `agents/transactoid.py`**
   ```python
   @function_tool
   def sync_transactions() -> dict[str, Any]:
   ```
   - **Status**: Returns "not_implemented"
   - **Needs**: 
     - Access to `SyncTool` instance (requires access_token management)
     - Return sync summary (counts of added/modified/removed)
     - Handle multiple items/access tokens

#### 7. **Multiple Items/Accounts**
   - **Current**: Single `access_token` per `SyncTool` instance
   - **Question**: How to sync multiple Plaid items?
   - **Recommendation**: 
     - One `SyncTool` instance per item
     - `scripts/run.py` can create multiple instances
     - Agent needs item management (future: `items` table)

#### 8. **Institution Metadata**
   - **Current**: `PlaidClient.get_item_info()` exists but not used in sync
   - **Question**: Should sync populate institution metadata?
   - **Recommendation**: Yes, for transaction persistence (`source="PLAID"`, `institution` field)

## Implementation Plan

### Phase 1: Core Sync Tool Enhancements

1. **Update `sync()` return type**
   - Return removed transactions separately
   - Consider returning a structured result object instead of tuple
   ```python
   @dataclass
   class SyncResult:
       added: list[CategorizedTransaction]
       modified: list[CategorizedTransaction]
       removed: list[dict[str, Any]]  # Plaid's removed format
       next_cursor: str
   ```

2. **Add cursor update method**
   ```python
   def update_cursor(self, cursor: str | None) -> None:
       """Update the cursor for next sync."""
       self._cursor = cursor
   ```

3. **Add error handling**
   - Wrap Plaid API calls in try/except
   - Handle categorization errors gracefully
   - Return error information in result

4. **Add `sync_all()` helper** (optional)
   ```python
   def sync_all(self, *, count: int = 500) -> SyncResult:
       """Sync all pages until complete."""
       # Loop until next_cursor is empty
   ```

### Phase 2: Integration with Scripts

1. **Implement `scripts/run.py::run_sync()`**
   - Initialize dependencies:
     - `PlaidClient.from_env()`
     - `Taxonomy.from_db(db)` 
     - `Categorizer(taxonomy, ...)`
     - `SyncTool(plaid_client, categorizer, access_token=access_token, cursor=cursor)`
   - Call `sync()` 
   - Optionally persist via `PersistTool` (if provided)
   - Print summary/logging

2. **Wire up `ui/cli.py::sync()`**
   - Call `run_sync()` with CLI args

### Phase 3: Agent Integration

1. **Update `agents/transactoid.py::sync_transactions()`**
   - Requires access token management (future: from DB)
   - Create `SyncTool` instance
   - Call `sync()`
   - Return structured summary:
     ```python
     {
         "status": "success",
         "added": len(added),
         "modified": len(modified),
         "removed": len(removed),
         "next_cursor": next_cursor,
     }
     ```

### Phase 4: Database Integration (Future)

1. **Add `items` table** (if needed)
   ```sql
   CREATE TABLE items (
       item_id SERIAL PRIMARY KEY,
       access_token TEXT NOT NULL UNIQUE,
       cursor TEXT,
       institution_name TEXT,
       last_synced_at TIMESTAMP,
       created_at TIMESTAMP DEFAULT NOW()
   );
   ```

2. **Store/retrieve cursors from DB**
   - `SyncTool` could accept a DB instance
   - Auto-save cursor after sync
   - Auto-load cursor on initialization

## Key Design Decisions Needed

### Decision 1: Return Type Structure
**Options:**
- A) Keep tuple `(list[CategorizedTransaction], str)` - simple but doesn't include removed
- B) Use `SyncResult` dataclass - more structured, includes removed
- C) Return dict - flexible but less type-safe

**Recommendation**: Option B - `SyncResult` dataclass

### Decision 2: Cursor Persistence
**Options:**
- A) Caller manages (current approach)
- B) `SyncTool` manages via DB (requires DB integration)
- C) `SyncTool` manages via file system

**Recommendation**: Option A for now, Option B in Phase 4

### Decision 3: Removed Transactions
**Options:**
- A) Return in result, caller handles
- B) `SyncTool` marks as deleted (requires DB)
- C) Ignore (not recommended)

**Recommendation**: Option A - return in result

### Decision 4: Error Handling Strategy
**Options:**
- A) Raise exceptions (fail fast)
- B) Return error in result object
- C) Log errors and return partial results

**Recommendation**: Option A for critical errors (network, auth), Option C for categorization errors

### Decision 5: Pagination Strategy
**Options:**
- A) Single page only (current)
- B) Auto-paginate in `sync()`
- C) Separate `sync_all()` method

**Recommendation**: Option C - keep `sync()` simple, add `sync_all()` helper

## Dependencies

### Required (Already Exist)
- ✅ `services/plaid_client.py::PlaidClient.sync_transactions()`
- ✅ `tools/categorize/categorizer_tool.py::Categorizer.categorize()`
- ✅ `models/transaction.py::Transaction`

### Required (Stubs Exist)
- ⚠️ `services/db.py::DB` (for future cursor persistence)
- ⚠️ `services/taxonomy.py::Taxonomy` (for categorizer)
- ⚠️ `tools/persist/persist_tool.py::PersistTool` (for saving results)

### Required (Need Implementation)
- ❌ `scripts/run.py::run_sync()` - stub only
- ❌ `ui/cli.py::sync()` - stub only
- ❌ `agents/transactoid.py::sync_transactions()` - stub only

## Testing Considerations

### Unit Tests Needed
1. `SyncTool.sync()` with mock PlaidClient and Categorizer
2. Cursor handling (initial vs incremental)
3. Error handling (Plaid errors, categorization errors)
4. Removed transactions handling
5. Empty results handling

### Integration Tests Needed
1. End-to-end sync → categorize → persist flow
2. Multiple sync calls with cursor progression
3. Error recovery scenarios

## Open Questions

1. **Should removed transactions be deleted from DB immediately, or marked as deleted?**
   - Consider: What if removal is temporary (Plaid bug)?
   - Consider: Audit trail requirements

2. **How to handle partial categorization failures?**
   - Should some transactions be categorized even if others fail?
   - Or fail entirely?

3. **Should sync be idempotent?**
   - If same cursor is used twice, should it return empty results?
   - Plaid should handle this, but worth verifying

4. **Rate limiting concerns?**
   - Plaid has rate limits
   - Should `SyncTool` handle retries with backoff?
   - Or let caller handle?

5. **Logging and observability?**
   - What level of logging is needed?
   - Should sync emit metrics/events?

6. **Transaction batching for categorization?**
   - Current: All transactions categorized in one batch
   - Should we batch for large syncs?
   - `Categorizer.categorize()` signature suggests it handles batches

## Next Steps

1. **Immediate**: Make design decisions on return type and removed transactions
2. **Short-term**: Implement Phase 1 enhancements to `SyncTool`
3. **Medium-term**: Implement Phase 2 (`scripts/run.py::run_sync()`)
4. **Long-term**: Implement Phase 3 (agent integration) and Phase 4 (DB cursor storage)

