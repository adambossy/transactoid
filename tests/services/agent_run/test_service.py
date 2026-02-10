"""Tests for AgentRunService."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from transactoid.adapters.clients.plaid import PlaidClientError
from transactoid.services.agent_run.service import AgentRunService, _extract_response
from transactoid.services.agent_run.types import AgentRunRequest


def _make_service():
    db = MagicMock()
    db.compact_schema_hint.return_value = {}
    db.fetch_categories.return_value = []

    taxonomy = MagicMock()
    taxonomy.to_prompt.return_value = {}
    taxonomy.from_nodes.return_value = taxonomy

    return AgentRunService(db=db, taxonomy=taxonomy, sql_dialect="sqlite")


class TestResolvePrompt:
    def test_raw_prompt_returned_as_is(self):
        service = _make_service()
        request = AgentRunRequest(prompt="Hello agent")

        result = service._resolve_prompt(request)

        assert result == "Hello agent"

    @patch("transactoid.services.agent_run.service.load_prompt")
    def test_prompt_key_loads_from_promptorium(self, mock_load):
        mock_load.return_value = "Loaded prompt"
        service = _make_service()
        request = AgentRunRequest(prompt_key="spending-report")

        result = service._resolve_prompt(request)

        assert result == "Loaded prompt"
        mock_load.assert_called_once_with("spending-report")

    def test_template_vars_injected(self):
        service = _make_service()
        request = AgentRunRequest(
            prompt="Date is {{CURRENT_DATE}} in {{CURRENT_MONTH}}",
            template_vars={
                "CURRENT_DATE": "2026-01-31",
                "CURRENT_MONTH": "January",
            },
        )

        result = service._resolve_prompt(request)

        assert result == "Date is 2026-01-31 in January"


class TestExtractResponse:
    def test_extracts_from_final_output_string(self):
        result = MagicMock()
        result.final_output = "Final report text"

        output = _extract_response(result)

        assert output == "Final report text"

    def test_extracts_from_final_output_text_attr(self):
        result = MagicMock()
        result.final_output = MagicMock(text="Report via text attr")

        output = _extract_response(result)

        assert output == "Report via text attr"

    def test_returns_empty_when_no_output(self):
        result = MagicMock()
        result.final_output = None
        result.new_items = []

        output = _extract_response(result)

        assert output == ""


class TestExecute:
    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.Runner")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_with_prompt_returns_success(
        self, _plaid, mock_transactoid, mock_runner, _upload
    ):
        mock_agent = MagicMock()
        mock_transactoid.return_value.create_agent.return_value = mock_agent

        mock_result = MagicMock()
        mock_result.final_output = "Report output"
        mock_runner.run = AsyncMock(return_value=mock_result)

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        result = asyncio.run(service.execute(request))

        assert result.success is True
        assert result.report_text == "Report output"
        assert result.error is None
        assert result.run_id is not None

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch(
        "transactoid.services.agent_run.service.Runner",
    )
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_handles_agent_error(
        self, _plaid, mock_transactoid, mock_runner, _upload
    ):
        mock_agent = MagicMock()
        mock_transactoid.return_value.create_agent.return_value = mock_agent
        mock_runner.run = AsyncMock(side_effect=RuntimeError("Agent crashed"))

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        result = asyncio.run(service.execute(request))

        assert result.success is False
        assert "Agent crashed" in (result.error or "")
        assert result.manifest.success is False
