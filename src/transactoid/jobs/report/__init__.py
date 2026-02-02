"""Report generation job for scheduled spending reports."""

from __future__ import annotations

from transactoid.jobs.report.html_renderer import render_report_html
from transactoid.jobs.report.runner import ReportResult, ReportRunner

__all__ = ["ReportResult", "ReportRunner", "render_report_html"]
