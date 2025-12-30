from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from openai import AsyncOpenAI
import yaml

from transactoid.adapters.cache.file_cache import FileCache, stable_key


@dataclass
class CriterionScore:
    """Score for a single criterion."""

    score: float  # 0.0 to 1.0
    reasoning: str


@dataclass
class JudgeResult:
    """Result of LLM judge evaluation."""

    numerical_consistency: CriterionScore
    conciseness: CriterionScore
    use_of_tables: CriterionScore
    accurate_formatting: CriterionScore
    snide_personality: CriterionScore
    overall_score: float  # average of all criteria
    passed: bool  # overall_score >= 0.80

    @property
    def all_scores(self) -> dict[str, float]:
        """Return all criterion scores as a dict."""
        return {
            "numerical_consistency": self.numerical_consistency.score,
            "conciseness": self.conciseness.score,
            "use_of_tables": self.use_of_tables.score,
            "accurate_formatting": self.accurate_formatting.score,
            "snide_personality": self.snide_personality.score,
        }


class LLMJudge:
    """LLM-based evaluator for agent responses."""

    def __init__(self, cache: FileCache | None = None) -> None:
        """Initialize judge with optional cache.

        Args:
            cache: FileCache instance for caching evaluations
        """
        self._cache = cache or FileCache()
        self._client = AsyncOpenAI()

    async def evaluate(
        self,
        conversation: str,
        ground_truth: dict[str, Any],
        expectations: list[str],
    ) -> JudgeResult:
        """Evaluate conversation using LLM judge.

        Args:
            conversation: Full Q&A conversation text
            ground_truth: Expected values for validation
            expectations: Human-readable expectations

        Returns:
            JudgeResult with scores for all criteria
        """
        # Check cache
        cache_key = stable_key(
            {
                "conversation": conversation,
                "ground_truth": ground_truth,
                "expectations": expectations,
                "model": "gpt-5.1",
                "version": "1.0",
            }
        )
        cached = self._cache.get("judge", cache_key)
        if cached:
            return self._parse_judge_response(cached)

        # Build prompt
        prompt = self._build_judge_prompt(conversation, ground_truth, expectations)

        # Call LLM (gpt-5.1)
        response = await self._call_judge_llm(prompt)

        # Cache and return
        self._cache.set("judge", cache_key, response)
        return self._parse_judge_response(response)

    def _build_judge_prompt(
        self,
        conversation: str,
        ground_truth: dict[str, Any],
        expectations: list[str],
    ) -> str:
        """Build evaluation prompt for LLM judge."""
        ground_truth_yaml = yaml.dump(ground_truth, default_flow_style=False)
        expectations_list = "\n".join(f"- {exp}" for exp in expectations)

        return f"""You are evaluating a personal finance agent's conversation with a user.

CONVERSATION:
{conversation}

GROUND TRUTH:
{ground_truth_yaml}

EXPECTATIONS:
{expectations_list}

Evaluate the conversation on these 5 criteria (0.0-1.0 each):

1. **Numerical Consistency**: Numbers match ground truth and remain consistent across turns
2. **Conciseness**: Responses are brief (1-3 sentences)
3. **Use of Tables**: Markdown tables used appropriately for structured data
4. **Accurate Formatting**: Currency ($XX.XX), percentages (XX%), dates formatted
   correctly
5. **Snide Personality**: Exhibits slightly snarky/snide tone while remaining helpful

Return your evaluation as JSON with this exact structure:
{{
  "numerical_consistency": {{"score": 0.0-1.0, "reasoning": "explanation"}},
  "conciseness": {{"score": 0.0-1.0, "reasoning": "explanation"}},
  "use_of_tables": {{"score": 0.0-1.0, "reasoning": "explanation"}},
  "accurate_formatting": {{"score": 0.0-1.0, "reasoning": "explanation"}},
  "snide_personality": {{"score": 0.0-1.0, "reasoning": "explanation"}}
}}"""

    async def _call_judge_llm(self, prompt: str) -> str:
        """Call LLM API for evaluation.

        Args:
            prompt: Evaluation prompt

        Returns:
            JSON string with evaluation results
        """
        response = await self._client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert evaluator. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,  # Deterministic evaluation
        )

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned no content")

        return content

    def _parse_judge_response(self, response: str) -> JudgeResult:
        """Parse LLM response into JudgeResult.

        Args:
            response: JSON string from LLM

        Returns:
            JudgeResult with parsed scores
        """
        # Parse JSON
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                data = json.loads(response[json_start:json_end])
            else:
                raise

        # Create CriterionScore objects
        numerical_consistency = CriterionScore(**data["numerical_consistency"])
        conciseness = CriterionScore(**data["conciseness"])
        use_of_tables = CriterionScore(**data["use_of_tables"])
        accurate_formatting = CriterionScore(**data["accurate_formatting"])
        snide_personality = CriterionScore(**data["snide_personality"])

        # Calculate overall score (average)
        overall_score = (
            numerical_consistency.score
            + conciseness.score
            + use_of_tables.score
            + accurate_formatting.score
            + snide_personality.score
        ) / 5.0

        # Check pass threshold
        passed = overall_score >= 0.80

        return JudgeResult(
            numerical_consistency=numerical_consistency,
            conciseness=conciseness,
            use_of_tables=use_of_tables,
            accurate_formatting=accurate_formatting,
            snide_personality=snide_personality,
            overall_score=overall_score,
            passed=passed,
        )
