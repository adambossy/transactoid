from __future__ import annotations

import argparse
import sys

from promptorium import load_prompt
from services import taxonomy_generator as tg


def run_build(yaml_path: str, model: str) -> bool:
    """
    Execute the taxonomy generation flow.
    Returns True if a new taxonomy was generated and stored, False if skipped.
    """
    merged_template = load_prompt("taxonomy-generator")
    input_yaml = tg.read_yaml_text(yaml_path)

    input_hash = tg.compute_sha256(tg._normalize_yaml_for_hash(input_yaml))
    prompt_hash = tg.compute_sha256(merged_template)

    latest_doc: str | None
    try:
        text = load_prompt("taxonomy-rules")
        latest_doc = str(text) if str(text).strip() else None
    except Exception:
        # If integration isn't configured, treat as if no prior version exists.
        latest_doc = None

    if not tg.should_regenerate(latest_doc, input_hash, prompt_hash):
        print("No changes detected. Skipping generation.")
        return False

    markdown_prompt = tg.render_prompt(merged_template, input_yaml)
    body_md = tg.call_openai(markdown_prompt, model=model)

    wrapped = tg.wrap_with_front_matter(
        body_md,
        {
            "taxonomy_version": "TBD",
            "input_yaml_sha256": input_hash,
            "prompt_sha256": prompt_hash,
            "model": model,
        },
    )

    # Store via Promptorium integration
    tg.store_generated(wrapped)
    print("Generated taxonomy and stored as the latest version.")
    return True


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the taxonomy via Promptorium + OpenAI."
    )
    parser.add_argument(
        "--yaml",
        dest="yaml_path",
        default="configs/taxonomy.yaml",
        help="Path to the input YAML file. Default: configs/taxonomy.yaml",
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


if __name__ == "__main__":
    raise SystemExit(main())
