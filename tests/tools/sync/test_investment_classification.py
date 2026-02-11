"""Tests for investment activity classification."""

from __future__ import annotations

from transactoid.tools.sync.investment_classification import (
    investment_activity_reporting_mode,
)


class TestInvestmentClassification:
    """Tests for investment_activity_reporting_mode function."""

    def test_zelle_payment_included(self) -> None:
        """Zelle payments should be included in default analytics."""
        # input
        transaction_type = "cash"
        transaction_subtype = None
        transaction_name = "Zelle payment to John"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_INCLUDE"

    def test_direct_deposit_included(self) -> None:
        """Direct deposits should be included in default analytics."""
        # input
        transaction_type = "cash"
        transaction_subtype = "deposit"
        transaction_name = "Direct Dep Payroll"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_INCLUDE"

    def test_ach_transfer_included(self) -> None:
        """ACH transfers should be included in default analytics."""
        # input
        transaction_type = "transfer"
        transaction_subtype = "ach"
        transaction_name = "ACH Transfer"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_INCLUDE"

    def test_dividend_excluded(self) -> None:
        """Dividend income should be excluded from default analytics."""
        # input
        transaction_type = "cash"
        transaction_subtype = "dividend"
        transaction_name = "Dividend"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_interest_income_excluded(self) -> None:
        """Interest income should be excluded from default analytics."""
        # input
        transaction_type = "cash"
        transaction_subtype = "interest"
        transaction_name = "Interest Income"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_buy_trade_excluded(self) -> None:
        """Buy trades should be excluded from default analytics."""
        # input
        transaction_type = "buy"
        transaction_subtype = None
        transaction_name = "Buy AAPL"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_sell_trade_excluded(self) -> None:
        """Sell trades should be excluded from default analytics."""
        # input
        transaction_type = "sell"
        transaction_subtype = None
        transaction_name = "Sell GOOGL"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_margin_interest_excluded(self) -> None:
        """Margin interest should be excluded from default analytics."""
        # input
        transaction_type = "fee"
        transaction_subtype = "margin"
        transaction_name = "Margin Interest"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_security_transfer_excluded(self) -> None:
        """Security transfers should be excluded from default analytics."""
        # input
        transaction_type = "transfer"
        transaction_subtype = None
        transaction_name = "Security Transfer"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_unknown_activity_included_by_default(self) -> None:
        """Unknown activity should default to INCLUDE (conservative approach)."""
        # input
        transaction_type = "unknown"
        transaction_subtype = None
        transaction_name = "Some Unknown Transaction"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_INCLUDE"

    def test_case_insensitive_matching(self) -> None:
        """Classification should be case-insensitive."""
        # input - uppercase name
        transaction_type = None
        transaction_subtype = None
        transaction_name = "DIVIDEND PAYMENT"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert
        assert result == "DEFAULT_EXCLUDE"

    def test_exclude_takes_precedence_over_include(self) -> None:
        """When a transaction matches both include and exclude keywords,
        exclude should take precedence for safety."""
        # input - contains both "dividend" (exclude) and "payment" (include)
        transaction_type = None
        transaction_subtype = None
        transaction_name = "Dividend payment"

        # act
        result = investment_activity_reporting_mode(
            transaction_type=transaction_type,
            transaction_subtype=transaction_subtype,
            transaction_name=transaction_name,
        )

        # assert - exclude wins
        assert result == "DEFAULT_EXCLUDE"
