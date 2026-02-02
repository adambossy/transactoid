"""Report runner for generating headless spending reports."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any

from agents import Runner, SQLiteSession
from agents.items import MessageOutputItem
from promptorium import load_prompt

from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.core import Taxonomy


@dataclass
class ReportResult:
    """Result of a report generation run."""

    report_text: str
    success: bool
    error: str | None
    duration_seconds: float
    metadata: dict[str, Any]


class ReportRunner:
    """Runs Transactoid agent headlessly to generate spending reports."""

    def __init__(
        self,
        db: DB,
        taxonomy: Taxonomy,
        plaid_client: PlaidClient | None = None,
        prompt_key: str = "spending-report",
    ) -> None:
        """Initialize report runner.

        Args:
            db: Database instance (should be PostgreSQL for production)
            taxonomy: Taxonomy instance
            plaid_client: Optional PlaidClient instance. If None, will be
                created from env when needed.
            prompt_key: Prompt key for loading report template
        """
        self._db = db
        self._taxonomy = taxonomy
        self._plaid_client = plaid_client
        self._prompt_key = prompt_key

    async def generate_report(self, report_month: str | None = None) -> ReportResult:
        """Generate a spending report using the headless agent.

        Args:
            report_month: Optional month in YYYY-MM format. If None, uses current month.

        Returns:
            ReportResult with report content and metadata
        """
        start = time.time()
        metadata: dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "prompt_key": self._prompt_key,
            "report_month": report_month or "current",
        }

        try:
            # Initialize Plaid client if not provided
            if self._plaid_client is None:
                try:
                    self._plaid_client = PlaidClient.from_env()
                except PlaidClientError as e:
                    return ReportResult(
                        report_text="",
                        success=False,
                        error=f"Failed to initialize Plaid client: {e}",
                        duration_seconds=time.time() - start,
                        metadata=metadata,
                    )

            # Create agent with PostgreSQL dialect
            transactoid = Transactoid(
                db=self._db,
                taxonomy=self._taxonomy,
                plaid_client=self._plaid_client,
            )
            agent = transactoid.create_agent(sql_dialect="postgresql")

            # Load the report prompt
            prompt = self._load_report_prompt(report_month)
            metadata["prompt_length"] = len(prompt)

            # Run the agent with the report prompt
            # Allow more turns since report generation involves multiple SQL queries
            session = SQLiteSession(session_id="report_job")
            result = await Runner.run(
                agent, input=prompt, session=session, max_turns=50
            )

            # Extract response
            response = self._extract_response(result)

            return ReportResult(
                report_text=response,
                success=True,
                error=None,
                duration_seconds=time.time() - start,
                metadata=metadata,
            )

        except Exception as e:
            return ReportResult(
                report_text="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
                metadata=metadata,
            )

    def _load_report_prompt(self, report_month: str | None = None) -> str:
        """Load and prepare the report prompt template.

        Args:
            report_month: Optional month in YYYY-MM format. If None, uses current month.

        Returns:
            Rendered prompt string
        """
        # Load base prompt from promptorium
        prompt = load_prompt(self._prompt_key)

        # Determine the target month
        if report_month:
            # Parse YYYY-MM format
            year, month = map(int, report_month.split("-"))
            month_name = calendar.month_name[month]
            # Use last day of the month as reference date
            last_day = calendar.monthrange(year, month)[1]
            date_str = f"{year}-{month:02d}-{last_day:02d}"
        else:
            # Use current date
            now = datetime.now()
            year = now.year
            month_name = now.strftime("%B")
            date_str = now.strftime("%Y-%m-%d")

        # Inject date information
        prompt = prompt.replace("{{CURRENT_DATE}}", date_str)
        prompt = prompt.replace("{{CURRENT_MONTH}}", month_name)
        prompt = prompt.replace("{{CURRENT_YEAR}}", str(year))

        return prompt

    def _extract_response(self, result: Any) -> str:
        """Extract final response text from agent result."""
        # Try to get from final_output first (standard way)
        if hasattr(result, "final_output") and result.final_output:
            if isinstance(result.final_output, str):
                return result.final_output
            # If final_output is a dict or object, try to get text
            if hasattr(result.final_output, "text"):
                return str(result.final_output.text)

        # Fallback: Find MessageOutputItem in result.new_items
        for item in result.new_items:
            if isinstance(item, MessageOutputItem):
                # Get text from content
                if hasattr(item, "content") and item.content:
                    for content_item in item.content:
                        if hasattr(content_item, "text"):
                            text: str = str(content_item.text)
                            return text
        return ""
