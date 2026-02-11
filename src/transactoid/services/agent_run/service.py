"""Core agent run orchestration service."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import time
import uuid

from agents import Agent, Runner, SQLiteSession
from agents.items import MessageOutputItem
from agents.result import RunResult
from loguru import logger
from promptorium import load_prompt

from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.adapters.storage.r2 import R2StorageError
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.services.agent_run.trace import download_trace, upload_trace
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    AgentRunResult,
    ArtifactRecord,
    RunManifest,
)
from transactoid.taxonomy.core import Taxonomy


class AgentRunService:
    """Executes headless agent runs and manages artifact output.

    Callers construct a service with shared infrastructure (DB, taxonomy),
    then call ``execute`` with an ``AgentRunRequest`` for each run.
    """

    def __init__(
        self,
        *,
        db: DB,
        taxonomy: Taxonomy,
        plaid_client: PlaidClient | None = None,
        sql_dialect: str = "postgresql",
    ) -> None:
        self._db = db
        self._taxonomy = taxonomy
        self._plaid_client = plaid_client
        self._sql_dialect = sql_dialect

    async def execute(self, request: AgentRunRequest) -> AgentRunResult:
        """Execute a single agent run from the given request.

        Args:
            request: Fully-specified run request DTO.

        Returns:
            AgentRunResult with report text, artifacts, and manifest.
        """
        run_id = uuid.uuid4().hex[:12]
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        trace_path = self._resolve_trace_path(request)

        try:
            return await self._execute_inner(
                request, run_id, started_at, start_mono, trace_path
            )
        finally:
            if trace_path.exists():
                trace_path.unlink(missing_ok=True)

    async def _execute_inner(
        self,
        request: AgentRunRequest,
        run_id: str,
        started_at: datetime,
        start_mono: float,
        trace_path: Path,
    ) -> AgentRunResult:
        """Run the agent and persist trace, returning the result."""
        try:
            plaid_client = self._resolve_plaid_client()
            agent = self._create_agent(plaid_client)
            prompt = self._resolve_prompt(request)
            response_text = await self._run_agent(
                agent, prompt, request.max_turns, trace_path
            )
        except Exception as exc:
            duration = time.monotonic() - start_mono
            finished_at = datetime.now(UTC)
            error_msg = str(exc)
            logger.bind(run_id=run_id).error("Agent run failed: {}", error_msg)
            manifest = RunManifest(
                run_id=run_id,
                parent_run_id=request.continue_run_id,
                prompt_key=request.prompt_key,
                started_at=started_at,
                finished_at=finished_at,
                success=False,
                error=error_msg,
            )
            trace_artifacts = _persist_trace(
                run_id=run_id, trace_path=trace_path, manifest=manifest
            )
            return AgentRunResult(
                run_id=run_id,
                success=False,
                report_text="",
                html_text=None,
                error=error_msg,
                duration_seconds=duration,
                manifest=manifest,
                artifacts=tuple(trace_artifacts),
            )

        duration = time.monotonic() - start_mono
        finished_at = datetime.now(UTC)
        logger.bind(run_id=run_id, duration=duration).info("Agent run completed")

        manifest = RunManifest(
            run_id=run_id,
            parent_run_id=request.continue_run_id,
            prompt_key=request.prompt_key,
            started_at=started_at,
            finished_at=finished_at,
            success=True,
            error=None,
        )

        trace_artifacts = _persist_trace(
            run_id=run_id, trace_path=trace_path, manifest=manifest
        )

        return AgentRunResult(
            run_id=run_id,
            success=True,
            report_text=response_text,
            html_text=None,
            error=None,
            duration_seconds=duration,
            manifest=manifest,
            artifacts=tuple(trace_artifacts),
        )

    def _resolve_plaid_client(self) -> PlaidClient | None:
        """Return the injected Plaid client, or try to build one from env."""
        if self._plaid_client is not None:
            return self._plaid_client
        try:
            return PlaidClient.from_env()
        except PlaidClientError:
            logger.warning("Plaid client not available; continuing without it")
            return None

    def _create_agent(self, plaid_client: PlaidClient | None) -> Agent[None]:
        """Build a Transactoid Agent instance."""
        transactoid = Transactoid(
            db=self._db,
            taxonomy=self._taxonomy,
            plaid_client=plaid_client,
        )
        return transactoid.create_agent(sql_dialect=self._sql_dialect)

    def _resolve_prompt(self, request: AgentRunRequest) -> str:
        """Load and render the prompt for the run.

        Handles both raw ``prompt`` and ``prompt_key`` paths, then applies
        any ``template_vars`` substitutions.
        """
        if request.prompt is not None:
            text = request.prompt
        else:
            assert request.prompt_key is not None  # noqa: S101
            text = load_prompt(request.prompt_key)

        for var_name, var_value in request.template_vars.items():
            text = text.replace(f"{{{{{var_name}}}}}", var_value)

        return text

    @staticmethod
    def _resolve_trace_path(request: AgentRunRequest) -> Path:
        """Get or create the trace database path.

        For continuation runs, downloads the prior trace from R2.
        For new runs, creates a temporary file.
        """
        if request.continue_run_id is not None:
            return download_trace(run_id=request.continue_run_id)
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        tmp.close()
        return Path(tmp.name)

    @staticmethod
    async def _run_agent(
        agent: Agent[None], prompt: str, max_turns: int, trace_path: Path
    ) -> str:
        """Execute the agent and extract the response text."""
        session = SQLiteSession(session_id="agent_run", db_path=trace_path)
        result = await Runner.run(
            agent, input=prompt, session=session, max_turns=max_turns
        )
        return _extract_response(result)


def _persist_trace(
    *,
    run_id: str,
    trace_path: Path,
    manifest: RunManifest,
) -> list[ArtifactRecord]:
    """Upload trace and manifest to R2, logging errors without raising."""
    try:
        return upload_trace(run_id=run_id, trace_path=trace_path, manifest=manifest)
    except (R2StorageError, OSError, json.JSONDecodeError) as exc:
        logger.error("Trace persistence failed for run {}: {}", run_id, exc)
        return []


def _extract_response(result: RunResult) -> str:
    """Extract final response text from an agent result."""
    output = result.final_output
    if output is not None:
        if isinstance(output, str):
            return output
        # Structured output with a .text attribute
        text = getattr(output, "text", None)
        if text is not None:
            return str(text)

    for item in result.new_items:
        if isinstance(item, MessageOutputItem):
            for content_item in item.content:
                text = getattr(content_item, "text", None)
                if text is not None:
                    return str(text)
    return ""
