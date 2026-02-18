"""Tests for agent run request/result types."""

from __future__ import annotations

import pytest

from transactoid.services.agent_run.types import AgentRunRequest, OutputTarget


class TestAgentRunRequest:
    def test_prompt_creates_valid_request(self):
        request = AgentRunRequest(prompt="Hello agent")

        assert request.prompt == "Hello agent"
        assert request.prompt_key is None

    def test_prompt_key_creates_valid_request(self):
        request = AgentRunRequest(prompt_key="report-monthly")

        assert request.prompt is None
        assert request.prompt_key == "report-monthly"

    def test_neither_prompt_nor_key_raises(self):
        with pytest.raises(ValueError, match="Either prompt or prompt_key"):
            AgentRunRequest()

    def test_both_prompt_and_key_raises(self):
        with pytest.raises(ValueError, match="Only one of"):
            AgentRunRequest(prompt="hello", prompt_key="report-monthly")

    def test_defaults(self):
        # input
        request = AgentRunRequest(prompt="test")

        # expected
        expected_output = {
            "save_md": True,
            "save_html": True,
            "output_targets": (OutputTarget.R2,),
            "email_recipients": (),
            "max_turns": 50,
            "continue_run_id": None,
            "local_dir": None,
        }

        # assert
        assert {
            "save_md": request.save_md,
            "save_html": request.save_html,
            "output_targets": request.output_targets,
            "email_recipients": request.email_recipients,
            "max_turns": request.max_turns,
            "continue_run_id": request.continue_run_id,
            "local_dir": request.local_dir,
        } == expected_output

    def test_template_vars_default_empty(self):
        request = AgentRunRequest(prompt="test")

        assert request.template_vars == {}
