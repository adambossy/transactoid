"""Tests for AgentRunService."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from transactoid.adapters.clients.plaid import PlaidClientError
from transactoid.adapters.storage.r2 import R2DownloadError
from transactoid.services.agent_run.service import (
    AgentRunService,
    _build_input_text,
    _extract_response,
)
from transactoid.services.agent_run.state import (
    ContinuationState,
    ConversationTurn,
    CorruptContinuationStateError,
)
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    ArtifactRecord,
    OutputTarget,
)


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

    @patch("transactoid.services.agent_run.service.upload_continuation_state")
    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.download_continuation_state")
    @patch("transactoid.services.agent_run.service.download_trace")
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_with_continue_loads_session_state_and_builds_continuation_input(
        self,
        _plaid,
        mock_transactoid,
        mock_load_config,
        mock_download_trace,
        mock_download_state,
        _upload_trace,
        mock_upload_state,
    ):
        mock_download_trace.return_value = MagicMock(exists=lambda: False)
        prior_state = ContinuationState(
            run_id="prior-run-abc",
            turns=[
                ConversationTurn(role="user", content="Prior user turn"),
                ConversationTurn(role="assistant", content="Prior assistant turn"),
            ],
        )
        mock_download_state.return_value = prior_state
        mock_upload_state.return_value = ArtifactRecord(
            artifact_type="session-state",
            key="agent-runs/new-run-id/session-state.json",
            target=OutputTarget.R2,
            content_type="application/json",
            size_bytes=100,
        )

        mock_runtime = _make_mock_runtime(final_text="Follow-up answer")
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(
            prompt="Follow-up question",
            continue_run_id="prior-run-abc",
        )

        result = asyncio.run(service.execute(request))

        assert result.success is True
        mock_download_state.assert_called_once_with(run_id="prior-run-abc")

        call_kwargs = mock_runtime.run.call_args.kwargs
        input_text = call_kwargs["input_text"]
        assert '<prior_turn role="user">Prior user turn</prior_turn>' in input_text
        asst_tag = '<prior_turn role="assistant">Prior assistant turn</prior_turn>'
        assert asst_tag in input_text
        assert "Follow-up question" in input_text

        session_key_used = mock_runtime.start_session.call_args.args[0]
        assert session_key_used == "prior-run-abc"

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.download_continuation_state")
    @patch("transactoid.services.agent_run.service.download_trace")
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_continue_missing_state_returns_failure_with_clear_error(
        self,
        _plaid,
        mock_transactoid,
        mock_load_config,
        mock_download_trace,
        mock_download_state,
        _upload_trace,
    ):
        mock_download_trace.return_value = MagicMock(exists=lambda: False)
        mock_download_state.side_effect = R2DownloadError("not found")

        mock_runtime = _make_mock_runtime()
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(
            prompt="Continue previous analysis",
            continue_run_id="missing-run-xyz",
        )

        result = asyncio.run(service.execute(request))

        assert result.success is False
        assert result.error is not None
        assert "Cannot continue" in result.error
        assert "missing-run-xyz" in result.error
        mock_runtime.run.assert_not_called()

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.download_continuation_state")
    @patch("transactoid.services.agent_run.service.download_trace")
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_continue_corrupt_state_returns_failure_with_clear_error(
        self,
        _plaid,
        mock_transactoid,
        mock_load_config,
        mock_download_trace,
        mock_download_state,
        _upload_trace,
    ):
        mock_download_trace.return_value = MagicMock(exists=lambda: False)
        mock_download_state.side_effect = CorruptContinuationStateError(
            "Corrupt continuation state for run corrupt-run-id"
        )

        mock_runtime = _make_mock_runtime()
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(
            prompt="Continue previous analysis",
            continue_run_id="corrupt-run-id",
        )

        result = asyncio.run(service.execute(request))

        assert result.success is False
        assert result.error is not None
        assert "Cannot continue" in result.error
        assert "corrupt-run-id" in result.error
        mock_runtime.run.assert_not_called()

    @patch("transactoid.services.agent_run.service.upload_continuation_state")
    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_persists_session_state_artifact_on_success(
        self,
        _plaid,
        mock_transactoid,
        mock_load_config,
        _upload_trace,
        mock_upload_state,
    ):
        state_artifact = ArtifactRecord(
            artifact_type="session-state",
            key="agent-runs/run-abc123/session-state.json",
            target=OutputTarget.R2,
            content_type="application/json",
            size_bytes=200,
        )
        mock_upload_state.return_value = state_artifact

        mock_runtime = _make_mock_runtime(final_text="Report output")
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Generate report")

        result = asyncio.run(service.execute(request))

        assert result.success is True
        mock_upload_state.assert_called_once()
        upload_call_kwargs = mock_upload_state.call_args.kwargs
        assert upload_call_kwargs["run_id"] == result.run_id
        uploaded_state = upload_call_kwargs["state"]
        assert isinstance(uploaded_state, ContinuationState)
        assert len(uploaded_state.turns) == 2
        assert uploaded_state.turns[0].role == "user"
        assert uploaded_state.turns[1].role == "assistant"
        assert state_artifact in result.artifacts


class TestGeminiRegressionNoCrash:
    """Regression: run-scheduled-report must not fail with 'create_agent is only
    supported with OpenAI runtime' when provider=gemini."""

    @patch("transactoid.services.agent_run.service.upload_trace", return_value=[])
    @patch("transactoid.services.agent_run.service.load_core_runtime_config_from_env")
    @patch("transactoid.services.agent_run.service.Transactoid")
    @patch(
        "transactoid.services.agent_run.service.PlaidClient.from_env",
        side_effect=PlaidClientError("no plaid"),
    )
    def test_execute_with_gemini_provider_does_not_raise_create_agent_error(
        self, _plaid, mock_transactoid, mock_load_config, _upload
    ):
        """Verify that calling execute() with provider=gemini succeeds and does not
        raise RuntimeError('create_agent is only supported with OpenAI runtime').

        Prior to the runtime selection refactor, run-scheduled-report would fail
        with this error whenever TRANSACTOID_AGENT_PROVIDER was set to gemini.
        """
        from transactoid.core.runtime.config import CoreRuntimeConfig

        gemini_config = CoreRuntimeConfig(
            provider="gemini",
            model="gemini-2.5-pro",
        )
        mock_load_config.return_value = gemini_config

        mock_runtime = _make_mock_runtime(final_text="Gemini scheduled report")
        mock_transactoid.return_value.create_runtime.return_value = mock_runtime

        service = _make_service()
        request = AgentRunRequest(prompt="Run the scheduled daily report")

        result = asyncio.run(service.execute(request))

        assert result.success is True
        assert result.report_text == "Gemini scheduled report"
        mock_transactoid.return_value.create_runtime.assert_called_once_with(
            runtime_config=gemini_config,
            sql_dialect="sqlite",
        )


class TestBuildInputText:
    def test_returns_prompt_unchanged_when_no_prior_state(self):
        output = _build_input_text(prompt="My prompt", prior_state=None)

        assert output == "My prompt"

    def test_returns_prompt_unchanged_when_prior_state_has_no_turns(self):
        prior_state = ContinuationState(run_id="run-abc", turns=[])

        output = _build_input_text(prompt="My prompt", prior_state=prior_state)

        assert output == "My prompt"

    def test_prepends_prior_turns_before_current_prompt(self):
        prior_state = ContinuationState(
            run_id="run-abc",
            turns=[
                ConversationTurn(role="user", content="Prior question"),
                ConversationTurn(role="assistant", content="Prior answer"),
            ],
        )

        output = _build_input_text(prompt="New question", prior_state=prior_state)

        assert '<prior_turn role="user">Prior question</prior_turn>' in output
        assert '<prior_turn role="assistant">Prior answer</prior_turn>' in output
        assert "<current_prompt>" in output
        assert "New question" in output
        prior_turn_pos = output.index("<prior_turn")
        current_prompt_pos = output.index("<current_prompt>")
        assert prior_turn_pos < current_prompt_pos
