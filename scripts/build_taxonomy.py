from __future__ import annotations

import argparse
import sys
from typing import Optional

from services.taxonomy_generator import (
    _normalize_yaml_for_hash,
    call_openai,
    compute_sha256,
    load_latest_generated_text,
    load_or_default_merged_template,
    read_yaml_text,
    render_prompt,
    should_regenerate,
    store_generated,
    wrap_with_front_matter,
)


def run_build(yaml_path: str, model: str) -> bool:
    """
    Execute the taxonomy generation flow.
    Returns True if a new taxonomy was generated and stored, False if skipped.
    """
    merged_template = load_or_default_merged_template()
    input_yaml = read_yaml_text(yaml_path)

    input_hash = compute_sha256(_normalize_yaml_for_hash(input_yaml))
    prompt_hash = compute_sha256(merged_template)

    latest_doc: Optional[str]
    try:
        latest_doc = load_latest_generated_text()
    except Exception:
        # If integration isn't configured, treat as if no prior version exists.
        latest_doc = None

    if not should_regenerate(latest_doc, input_hash, prompt_hash):
        print("No changes detected. Skipping generation.")
        return False

    markdown_prompt = render_prompt(merged_template, input_yaml)
    body_md = call_openai(markdown_prompt, model=model)

    wrapped = wrap_with_front_matter(
        body_md,
        {
            "taxonomy_version": "TBD",
            "input_yaml_sha256": input_hash,
            "prompt_sha256": prompt_hash,
            "model": model,
        },
    )

    # Store via Promptorium integration
    store_generated(wrapped)
    print("Generated taxonomy and stored as the latest version.")
    return True


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the taxonomy via Promptorium + OpenAI."
    )
    parser.add_argument(
        "--yaml",
        dest="yaml_path",
        default="config/taxonomy.yaml",
        help="Path to the input YAML file. Default: config/taxonomy.yaml",
    )
    parser.add_argument(
        "--model",
        dest="model",
        default="gpt-4o",
        help="OpenAI model to use. Default: gpt-4o",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv or sys.argv[1:])
    try:
        run_build(ns.yaml_path, ns.model)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - surfaced for CLI usage
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
