"""Tests for the output pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from transactoid.services.agent_run.pipeline import OutputPipeline
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    OutputTarget,
)


class TestOutputPipelineLocal:
    def test_local_target_writes_md_and_html(self, tmp_path):
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=True,
            output_targets=(OutputTarget.LOCAL,),
            local_dir=str(tmp_path),
        )
        pipeline = OutputPipeline()

        with patch(
            "transactoid.services.agent_run.pipeline.render_report_html",
            return_value="<html>Report</html>",
        ):
            html_text, artifacts = pipeline.process(
                report_text="# Report", request=request, run_id="abc123"
            )

        assert html_text == "<html>Report</html>"
        assert len(artifacts) == 2

        md_artifact = next(a for a in artifacts if a.artifact_type == "report-md")
        html_artifact = next(a for a in artifacts if a.artifact_type == "report-html")

        assert md_artifact.target == OutputTarget.LOCAL
        assert html_artifact.target == OutputTarget.LOCAL
        assert (tmp_path / "abc123" / "report.md").exists()
        assert (tmp_path / "abc123" / "report.html").exists()
        assert (tmp_path / "abc123" / "report.md").read_text() == "# Report"

    def test_local_target_md_only(self, tmp_path):
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=False,
            output_targets=(OutputTarget.LOCAL,),
            local_dir=str(tmp_path),
        )
        pipeline = OutputPipeline()

        html_text, artifacts = pipeline.process(
            report_text="# Report", request=request, run_id="run1"
        )

        assert html_text is None
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "report-md"
        assert (tmp_path / "run1" / "report.md").exists()
        assert not (tmp_path / "run1" / "report.html").exists()


class TestOutputPipelineR2:
    @patch("transactoid.services.agent_run.pipeline.upload_artifact")
    @patch(
        "transactoid.services.agent_run.pipeline.render_report_html",
        return_value="<html>Styled</html>",
    )
    def test_r2_target_uploads_md_and_html(self, _render, mock_upload):
        mock_upload.return_value = MagicMock(
            key="report-md/20260210T033800Z-report-md",
            content_type="text/markdown; charset=utf-8",
        )
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=True,
            output_targets=(OutputTarget.R2,),
        )
        pipeline = OutputPipeline()

        html_text, artifacts = pipeline.process(
            report_text="# Report", request=request, run_id="abc123"
        )

        assert html_text == "<html>Styled</html>"
        assert mock_upload.call_count == 2

    @patch("transactoid.services.agent_run.pipeline.upload_artifact")
    def test_r2_target_md_only(self, mock_upload):
        mock_upload.return_value = MagicMock(
            key="report-md/test-key",
            content_type="text/markdown; charset=utf-8",
        )
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=False,
            output_targets=(OutputTarget.R2,),
        )
        pipeline = OutputPipeline()

        html_text, artifacts = pipeline.process(
            report_text="# Report", request=request, run_id="abc123"
        )

        assert html_text is None
        assert mock_upload.call_count == 1


class TestOutputPipelineNoTargets:
    def test_no_targets_returns_empty_artifacts(self):
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=False,
            output_targets=(),
        )
        pipeline = OutputPipeline()

        html_text, artifacts = pipeline.process(
            report_text="# Report", request=request, run_id="abc123"
        )

        assert html_text is None
        assert len(artifacts) == 0
