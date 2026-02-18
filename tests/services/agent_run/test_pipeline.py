"""Tests for the output pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from transactoid.services.agent_run.pipeline import (
    OutputPipeline,
    _validate_html_document,
)
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    OutputTarget,
)


class TestOutputPipelineLocal:
    @patch("transactoid.services.agent_run.pipeline._render_html_with_gemini")
    def test_local_target_writes_md_and_html(
        self, mock_render_html: MagicMock, tmp_path: Path
    ) -> None:
        # input
        input_data = {
            "report_text": "# Report",
            "run_id": "abc123",
        }

        # helper setup
        mock_render_html.return_value = (
            "<!DOCTYPE html><html><head></head><body><h1>Report</h1></body></html>"
        )
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=True,
            output_targets=(OutputTarget.LOCAL,),
            local_dir=str(tmp_path),
        )
        pipeline = OutputPipeline()

        # act
        output = pipeline.process(
            report_text=input_data["report_text"],
            request=request,
            run_id=input_data["run_id"],
        )

        # expected
        expected_output = (True, 2)

        # assert
        assert (output[0] is not None, len(output[1])) == expected_output

    def test_local_target_md_only(self, tmp_path: Path) -> None:
        # input
        input_data = {
            "report_text": "# Report",
            "run_id": "run1",
        }

        # helper setup
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=False,
            output_targets=(OutputTarget.LOCAL,),
            local_dir=str(tmp_path),
        )
        pipeline = OutputPipeline()

        # act
        output = pipeline.process(
            report_text=input_data["report_text"],
            request=request,
            run_id=input_data["run_id"],
        )

        # expected
        expected_output = (None, 1)

        # assert
        assert (output[0], len(output[1])) == expected_output


class TestOutputPipelineR2:
    @patch("transactoid.services.agent_run.pipeline.upload_artifact")
    @patch("transactoid.services.agent_run.pipeline._render_html_with_gemini")
    def test_r2_target_uploads_md_and_html(
        self, mock_render_html: MagicMock, mock_upload: MagicMock
    ) -> None:
        # input
        input_data = {
            "report_text": "# Report",
            "run_id": "abc123",
        }

        # helper setup
        mock_render_html.return_value = (
            "<!DOCTYPE html><html><head></head><body><h1>Report</h1></body></html>"
        )
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

        # act
        output = pipeline.process(
            report_text=input_data["report_text"],
            request=request,
            run_id=input_data["run_id"],
        )

        # expected
        expected_output = (2, 2)

        # assert
        assert (len(output[1]), mock_upload.call_count) == expected_output


class TestOutputPipelineNoTargets:
    def test_no_targets_returns_empty_artifacts(self) -> None:
        # input
        input_data = {
            "report_text": "# Report",
            "run_id": "abc123",
        }

        # helper setup
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=False,
            output_targets=(),
        )
        pipeline = OutputPipeline()

        # act
        output = pipeline.process(
            report_text=input_data["report_text"],
            request=request,
            run_id=input_data["run_id"],
        )

        # expected
        expected_output = (None, 0)

        # assert
        assert (output[0], len(output[1])) == expected_output


class TestOutputPipelineFailures:
    @patch("transactoid.services.agent_run.pipeline._render_html_with_gemini")
    def test_save_html_raises_when_renderer_fails(
        self, mock_render_html: MagicMock
    ) -> None:
        # input
        input_data = {
            "report_text": "# Report",
            "run_id": "abc123",
        }

        # helper setup
        mock_render_html.side_effect = RuntimeError("Gemini render failed")
        request = AgentRunRequest(
            prompt="test",
            save_md=True,
            save_html=True,
            output_targets=(OutputTarget.R2,),
        )
        pipeline = OutputPipeline()

        # act / assert
        with pytest.raises(RuntimeError, match="Gemini render failed"):
            pipeline.process(
                report_text=input_data["report_text"],
                request=request,
                run_id=input_data["run_id"],
            )


class TestHtmlValidation:
    def test_validate_html_document_accepts_full_document(self) -> None:
        # input
        input_data = (
            "<!DOCTYPE html><html><head><title>x</title></head>"
            "<body><h1>Report</h1></body></html>"
        )

        # act
        output = _validate_html_document(html_text=input_data)

        # expected
        expected_output = input_data

        # assert
        assert output == expected_output

    def test_validate_html_document_rejects_fragment(self) -> None:
        # input
        input_data = "<body><h1>Report</h1></body>"

        # act / assert
        with pytest.raises(RuntimeError, match="full HTML document"):
            _validate_html_document(html_text=input_data)
