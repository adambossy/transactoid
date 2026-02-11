"""Tests for Plaid investments methods."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from transactoid.adapters.clients.plaid import PlaidClient


class TestPlaidClientInvestments:
    """Tests for PlaidClient investments functionality."""

    def test_create_link_token_with_investments_consent(self) -> None:
        """Link token should include required_if_supported_products."""
        # input
        user_id = "test-user"
        redirect_uri = "https://localhost:8443/callback"
        products = ["transactions"]
        required_if_supported_products = ["investments"]

        # setup
        client = PlaidClient(
            client_id="test_client_id",
            secret="test_secret",
            env="sandbox",
        )

        # Mock the _post method
        with patch.object(client, "_post") as mock_post:
            mock_post.return_value = {"link_token": "test-link-token"}

            # act
            result = client.create_link_token(
                user_id=user_id,
                redirect_uri=redirect_uri,
                products=products,
                required_if_supported_products=required_if_supported_products,
            )

            # expected
            expected_token = "test-link-token"  # noqa: S105

            # assert
            assert result == expected_token

            # Verify the payload includes required_if_supported_products
            call_args = mock_post.call_args
            payload = call_args[0][1]
            assert payload["required_if_supported_products"] == ["investments"]

    def test_create_link_token_update_mode_with_access_token(self) -> None:
        """Update-mode link token should include access_token."""
        # input
        user_id = "test-user"
        redirect_uri = "https://localhost:8443/callback"
        products = ["transactions"]
        required_if_supported_products = ["investments"]
        access_token = "access-sandbox-test-token"  # noqa: S105

        # setup
        client = PlaidClient(
            client_id="test_client_id",
            secret="test_secret",
            env="sandbox",
        )

        # Mock the _post method
        with patch.object(client, "_post") as mock_post:
            mock_post.return_value = {"link_token": "test-update-link-token"}

            # act
            result = client.create_link_token(
                user_id=user_id,
                redirect_uri=redirect_uri,
                products=products,
                required_if_supported_products=required_if_supported_products,
                access_token=access_token,
            )

            # expected
            expected_token = "test-update-link-token"  # noqa: S105

            # assert
            assert result == expected_token

            # Verify the payload includes access_token for update mode
            call_args = mock_post.call_args
            payload = call_args[0][1]
            assert payload["access_token"] == access_token
            assert payload["required_if_supported_products"] == ["investments"]

    def test_get_investment_transactions(self) -> None:
        """get_investment_transactions should return formatted response."""
        # input
        access_token = "access-sandbox-test"  # noqa: S105
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)

        # setup
        client = PlaidClient(
            client_id="test_client_id",
            secret="test_secret",
            env="sandbox",
        )

        mock_response = {
            "investment_transactions": [
                {
                    "investment_transaction_id": "inv-txn-1",
                    "account_id": "account-123",
                    "amount": 100.50,
                    "date": "2024-01-15",
                    "name": "Dividend",
                    "type": "cash",
                    "subtype": "dividend",
                }
            ],
            "securities": [
                {"security_id": "sec-1", "name": "AAPL", "ticker_symbol": "AAPL"}
            ],
            "total_investment_transactions": 1,
        }

        # Mock the _post method
        with patch.object(client, "_post") as mock_post:
            mock_post.return_value = mock_response

            # act
            result = client.get_investment_transactions(
                access_token,
                start_date=start_date,
                end_date=end_date,
            )

            # assert
            assert "investment_transactions" in result
            assert "securities" in result
            assert len(result["investment_transactions"]) == 1
            assert (
                result["investment_transactions"][0]["investment_transaction_id"]
                == "inv-txn-1"
            )

    def test_get_investment_holdings(self) -> None:
        """get_investment_holdings should return formatted response."""
        # input
        access_token = "access-sandbox-test"  # noqa: S105

        # setup
        client = PlaidClient(
            client_id="test_client_id",
            secret="test_secret",
            env="sandbox",
        )

        mock_response = {
            "holdings": [
                {
                    "account_id": "account-123",
                    "security_id": "sec-1",
                    "quantity": 10.0,
                    "institution_price": 150.0,
                    "institution_value": 1500.0,
                }
            ],
            "securities": [
                {"security_id": "sec-1", "name": "AAPL", "ticker_symbol": "AAPL"}
            ],
        }

        # Mock the _post method
        with patch.object(client, "_post") as mock_post:
            mock_post.return_value = mock_response

            # act
            result = client.get_investment_holdings(access_token)

            # assert
            assert "holdings" in result
            assert "securities" in result
            assert len(result["holdings"]) == 1
            assert result["holdings"][0]["quantity"] == 10.0
