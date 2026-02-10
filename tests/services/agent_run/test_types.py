"""Tests for agent run request/result types."""

from __future__ import annotations

import pytest

from transactoid.services.agent_run.types import (
    AgentRunRequest,
    OutputTarget,
)


class TestAgentRunRequest:
    def test_prompt_creates_valid_request(self):
        request = AgentRunRequest(prompt="Hello agent")

        assert request.prompt == "Hello agent"
        assert request.prompt_key is None

    def test_prompt_key_creates_valid_request(self):
        request = AgentRunRequest(prompt_key="spending-report")

        assert request.prompt is None
        assert request.prompt_key == "spending-report"

    def test_neither_prompt_nor_key_raises(self):
        with pytest.raises(ValueError, match="Either prompt or prompt_key"):
            AgentRunRequest()

    def test_both_prompt_and_key_raises(self):
        with pytest.raises(ValueError, match="Only one of"):
            AgentRunRequest(prompt="hello", prompt_key="spending-report")

    def test_defaults(self):
        request = AgentRunRequest(prompt="test")

        assert request.save_md is True
        assert request.save_html is True
        assert request.output_targets == (OutputTarget.R2,)
        assert request.email_recipients == ()
        assert request.max_turns == 50
        assert request.continue_run_id is None
        assert request.local_dir is None

    def test_template_vars_default_empty(self):
        request = AgentRunRequest(prompt="test")

        assert request.template_vars == {}

    def test_custom_output_targets(self):
        request = AgentRunRequest(
            prompt="test",
            output_targets=(OutputTarget.LOCAL,),
            local_dir=".transactoid/test-out",
        )

        assert request.output_targets == (OutputTarget.LOCAL,)
        assert request.local_dir == ".transactoid/test-out"
