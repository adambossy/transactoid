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


def _make_mock_runtime(*, final_text: str = "Report output") -> MagicMock:
    mock_core_result = MagicMock()
    mock_core_result.final_text = final_text

    mock_session = MagicMock()

    mock_runtime = MagicMock()
    mock_runtime.start_session.return_value = mock_session
    mock_runtime.run = AsyncMock(return_value=mock_core_result)
    mock_runtime.close = AsyncMock()
    return mock_runtime


class TestExecute:
    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_with_prompt_returns_success(
        self, _plaid, mock_transactoid, mock_load_config, _upload
    ):
        mock_runtime = _make_mock_runtime(final_text="Report output")
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        result = asyncio.run(service.execute(request))

        assert result.success is True
        assert result.report_text == "Report output"
        assert result.error is None
        assert result.run_id is not None

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_handles_agent_error(
        self, _plaid, mock_transactoid, mock_load_config, _upload
    ):
        mock_runtime = MagicMock()
        mock_runtime.start_session.return_value = MagicMock()
        mock_runtime.run = AsyncMock(side_effect=RuntimeError("Agent crashed"))
        mock_runtime.close = AsyncMock()
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        result = asyncio.run(service.execute(request))

        assert result.success is False
        assert "Agent crashed" in (result.error or "")
        assert result.manifest.success is False

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_uses_create_runtime_for_provider_from_env(
        self, _plaid, mock_transactoid, mock_load_config, _upload
    ):
        mock_runtime = _make_mock_runtime()
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        asyncio.run(service.execute(request))

        mock_transactoid.return_value.create_runtime.assert_called_once()
        mock_load_config.assert_called_once()

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_with_gemini_provider_succeeds_when_core_runtime_returns_text(
        self, _plaid, mock_transactoid, mock_load_config, _upload
    ):
        from transactoid.core.runtime.config import CoreRuntimeConfig

        gemini_config = CoreRuntimeConfig(
            provider="gemini",
            model="gemini-2.5-pro",
        )
        mock_load_config.return_value = gemini_config

        mock_runtime = _make_mock_runtime(final_text="Gemini report text")
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Summarize spending")

        result = asyncio.run(service.execute(request))

        assert result.success is True
        assert result.report_text == "Gemini report text"
        mock_transactoid.return_value.create_runtime.assert_called_once_with(
            runtime_config=gemini_config,
            sql_dialect="sqlite",
        )
