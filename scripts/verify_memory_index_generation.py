from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from transactoid.memory.index_generation import generate_memory_index_markdown


def _call_gemini_text(*, prompt: str, model: str) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required")

    try:
        from google.genai.client import Client
    except ImportError as e:
        raise RuntimeError("google-genai package is required") from e

    client = Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    return str(response)


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Judge did not return JSON")

    payload = text[start : end + 1]
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Judge output was not a JSON object")
    return parsed


def _judge_prompt(*, baseline: str, candidate: str) -> str:
    return f"""
You are evaluating whether a generated markdown memory index is semantically
similar to a baseline.

Rubric:
- Required sections and heading intent align.
- File/path coverage is substantially equivalent.
- Annotation bullets preserve the same meaning, even if wording differs.

Respond with JSON only using this schema:
{{
  "passes": boolean,
  "summary": string,
  "section_alignment": number,
  "path_coverage": number,
  "semantic_similarity": number,
  "issues": [string]
}}

Scoring guidance:
- Scores are floats from 0.0 to 1.0.
- Set passes=true only if:
  - section_alignment >= 0.9
  - path_coverage >= 0.9
  - semantic_similarity >= 0.85

Baseline markdown:
```markdown
{baseline}
```

Candidate markdown:
```markdown
{candidate}
```
""".strip()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate memory/index.md via Gemini prompt and judge similarity "
            "against current memory/index.md."
        )
    )
    parser.add_argument(
        "--memory-dir",
        default="memory",
        help="Path to memory directory. Default: memory",
    )
    parser.add_argument(
        "--model",
        default="gemini-3-pro-preview",
        help="Gemini model for generation. Default: gemini-3-pro-preview",
    )
    parser.add_argument(
        "--judge-model",
        default="gemini-3-pro-preview",
        help="Gemini model for semantic judging. Default: gemini-3-pro-preview",
    )
    parser.add_argument(
        "--prompt-key",
        default="generate-memory-index",
        help="Promptorium key for generation prompt.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    memory_dir = Path(args.memory_dir)
    baseline_path = memory_dir / "index.md"

    baseline = baseline_path.read_text() if baseline_path.exists() else ""
    candidate = generate_memory_index_markdown(
        memory_dir=memory_dir,
        model=args.model,
        prompt_key=args.prompt_key,
    )

    judge_input = _judge_prompt(baseline=baseline, candidate=candidate)
    judge_raw = _call_gemini_text(prompt=judge_input, model=args.judge_model)
    verdict = _extract_json(judge_raw)

    print("Memory index generation verification")
    print(f"- model: {args.model}")
    print(f"- judge_model: {args.judge_model}")
    print(f"- passes: {verdict.get('passes')}")
    print(f"- summary: {verdict.get('summary', '')}")
    print(f"- section_alignment: {verdict.get('section_alignment')}")
    print(f"- path_coverage: {verdict.get('path_coverage')}")
    print(f"- semantic_similarity: {verdict.get('semantic_similarity')}")

    issues = verdict.get("issues", [])
    if isinstance(issues, list) and issues:
        print("- issues:")
        for issue in issues:
            print(f"  - {issue}")

    if verdict.get("passes") is True:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
