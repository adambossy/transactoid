from __future__ import annotations

from evals.core.eval_harness import EvalHarness
from evals.core.headless_runner import AgentTurn, ConversationResult


def _create_conversation_result(
    tool_names_by_turn: list[list[str]],
) -> ConversationResult:
    turns = []
    for idx, tool_names in enumerate(tool_names_by_turn, start=1):
        tool_calls = [
            {"name": tool_name, "arguments": {}, "result": {}}
            for tool_name in tool_names
        ]
        turns.append(
            AgentTurn(
                question=f"question {idx}",
                response=f"response {idx}",
                tool_calls=tool_calls,
                reasoning="",
                duration_seconds=0.1,
            )
        )
    return ConversationResult(turns=turns, total_duration_seconds=0.2)


def test_eval_harness_evaluate_tool_limits_flags_run_sql_above_max() -> None:
    # input
    input_data = {
        "tool_limits": {
            "run_sql": {
                "min": 1,
                "max": 2,
            }
        }
    }

    # helper setup
    harness = EvalHarness("evals/config/questions_test.yaml")
    conversation_result = _create_conversation_result(
        [["list_accounts", "run_sql"], ["run_sql", "run_sql"]]
    )

    # act
    output = harness._evaluate_tool_limits(
        question_config=input_data,
        conversation_result=conversation_result,
    )

    # expected
    expected_output: tuple[dict[str, int], list[str]] = (
        {"run_sql": 3},
        ["run_sql: expected at most 2 calls, got 3"],
    )

    # assert
    assert output == expected_output


def test_eval_harness_evaluate_tool_limits_passes_when_run_sql_within_range() -> None:
    # input
    input_data = {
        "tool_limits": {
            "run_sql": {
                "min": 1,
                "max": 2,
            }
        }
    }

    # helper setup
    harness = EvalHarness("evals/config/questions_test.yaml")
    conversation_result = _create_conversation_result(
        [["list_accounts", "run_sql"], ["sync_transactions"]]
    )

    # act
    output = harness._evaluate_tool_limits(
        question_config=input_data,
        conversation_result=conversation_result,
    )

    # expected
    expected_output: tuple[dict[str, int], list[str]] = ({"run_sql": 1}, [])

    # assert
    assert output == expected_output
