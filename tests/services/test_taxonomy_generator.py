from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from services import taxonomy_generator as tg
from scripts.build_taxonomy import run_build


def test_normalized_yaml_hash_is_stable_for_whitespace() -> None:
    yaml_a = """
    parents:
      - name: A
        children:
          - X
          - Y
    """
    yaml_b = "parents:\n - name: A\n   children:\n    - X\n    - Y\n"
    h1 = tg.compute_sha256(tg._normalize_yaml_for_hash(yaml_a))
    h2 = tg.compute_sha256(tg._normalize_yaml_for_hash(yaml_b))
    assert h1 == h2


def test_should_regenerate_false_when_hashes_match() -> None:
    input_hash = "aaaabbbbcccc"
    prompt_hash = "111122223333"
    latest_doc = f"""---
taxonomy_version: "v1"
input_yaml_sha256: "{input_hash}"
prompt_sha256: "{prompt_hash}"
model: "gpt-4o"
created_at: "2025-01-01T00:00:00Z"
---

Body
"""
    assert tg.should_regenerate(latest_doc, input_hash, prompt_hash) is False


def test_should_regenerate_true_when_input_hash_changes() -> None:
    input_hash = "aaaabbbbcccc"
    prompt_hash = "111122223333"
    latest_doc = f"""---
taxonomy_version: "v1"
input_yaml_sha256: "DIFFERENT"
prompt_sha256: "{prompt_hash}"
model: "gpt-4o"
created_at: "2025-01-01T00:00:00Z"
---

Body
"""
    assert tg.should_regenerate(latest_doc, input_hash, prompt_hash) is True


def test_wrap_with_front_matter_contains_required_keys() -> None:
    body = "# Title\nSome content."
    wrapped = tg.wrap_with_front_matter(
        body,
        {
            "taxonomy_version": "TBD",
            "input_yaml_sha256": "ihash",
            "prompt_sha256": "phash",
            "model": "gpt-4o",
            "created_at": "2025-01-01T00:00:00Z",
        },
    )
    assert wrapped.startswith("---\n")
    assert "input_yaml_sha256:" in wrapped
    assert "prompt_sha256:" in wrapped
    assert "model:" in wrapped
    assert wrapped.count("---") >= 2
    assert "Some content." in wrapped


def test_generation_flow_stores_when_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prepare input YAML file
    yaml_path = tmp_path / "in.yaml"
    yaml_path.write_text(
        "parents:\n  - name: Test\n    children:\n      - X\n      - Y\n",
        encoding="utf-8",
    )

    # Force a deterministic template and OpenAI result
    monkeypatch.setattr(
        tg, "load_prompt_text", lambda key: "TEMPLATE\n{input_yaml}\nEND" if key == "taxonomy-generator" else ""
    )
    monkeypatch.setattr(
        tg, "call_openai", lambda markdown_prompt, model: "Generated Body"
    )

    stored: List[str] = []
    monkeypatch.setattr(tg, "load_latest_generated_text", lambda: None)
    monkeypatch.setattr(tg, "store_generated", lambda md: stored.append(md))

    did_generate = run_build(str(yaml_path), model="gpt-4o")
    assert did_generate is True
    assert len(stored) == 1
    out = stored[0]
    # Basic sanity checks
    assert out.startswith("---\n")
    assert "Generated Body" in out
    assert re.search(r"input_yaml_sha256:\s*\"?[0-9a-f]{64}\"?", out) is not None
    assert re.search(r"prompt_sha256:\s*\"?[0-9a-f]{64}\"?", out) is not None


def test_generation_flow_skips_when_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prepare input YAML file
    yaml_path = tmp_path / "in.yaml"
    yaml_text = "parents:\n  - name: Test\n    children:\n      - X\n      - Y\n"
    yaml_path.write_text(yaml_text, encoding="utf-8")

    # Deterministic template
    template = "TEMPLATE\n{input_yaml}\nEND"
    monkeypatch.setattr(tg, "load_prompt_text", lambda key: template if key == "taxonomy-generator" else "")

    inp_hash = tg.compute_sha256(tg._normalize_yaml_for_hash(yaml_text))
    prm_hash = tg.compute_sha256(template)
    latest_doc = f"""---
taxonomy_version: "v9"
input_yaml_sha256: "{inp_hash}"
prompt_sha256: "{prm_hash}"
model: "gpt-4o"
created_at: "2025-01-01T00:00:00Z"
---

Body
"""

    monkeypatch.setattr(tg, "load_latest_generated_text", lambda: latest_doc)

    def _fail_on_store(_: str) -> None:
        raise AssertionError("store_generated should not be called when unchanged")

    monkeypatch.setattr(tg, "store_generated", _fail_on_store)
    # Avoid actual OpenAI call if code accidentally reaches it
    monkeypatch.setattr(tg, "call_openai", lambda *_args, **_kwargs: "NOOP")

    did_generate = run_build(str(yaml_path), model="gpt-4o")
    assert did_generate is False
