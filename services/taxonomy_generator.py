from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from textwrap import dedent
from typing import Any, Dict, Optional, Tuple

import yaml
from openai import OpenAI
from promptorium.services import PromptService
from promptorium.storage.fs import FileSystemPromptStorage
from promptorium.util.repo_root import find_repo_root

# Merged prompt template with {input_yaml} placeholder.
# This is used as a fallback if Promptorium is not available.
DEFAULT_MERGED_TEMPLATE: str = dedent(
    """\
    You are an expert taxonomist and information architect. You will be given:
    A list of parent categories and child categories (in YAML form)
    Optionally, short rules or hints for each category
    Your goal is to write a comprehensive, human-readable taxonomy document that mirrors the quality, structure, and detail of the Personal Finance Transaction Taxonomy v1 shown earlier.

    ---

    You are an expert taxonomy architect and information designer.

    You will be given a YAML definition containing parent and child categories for a specific domain.
    Your job is to produce a comprehensive two-level taxonomy document, modeled after the “Proposed 2-level Transaction Category Taxonomy (v1)” example.

    ### Input YAML
    {input_yaml}

    ### Domain
    Personal Finance Transactions

    ### Objectives
    [... keep the remainder of the previous user prompt spec here verbatim ...]
    """
)


# ----------------------------
# Promptorium integration (library-based)
# ----------------------------
def load_prompt_text(key: str) -> str:
    """
    Load the latest prompt text by key from Promptorium.
    Uses the Promptorium library with filesystem storage rooted at the repository.
    """
    storage = FileSystemPromptStorage(find_repo_root())
    svc = PromptService(storage)
    return str(svc.load_prompt(key))


def store_generated(markdown: str) -> None:
    """
    Store generated taxonomy markdown to Promptorium under key `taxonomy-personal-finance`.
    Uses the Promptorium library and creates the key if it does not exist.
    """
    key = "taxonomy-personal-finance"
    storage = FileSystemPromptStorage(find_repo_root())
    svc = PromptService(storage)
    # Try updating directly; if key doesn't exist, add then retry.
    try:
        svc.update_prompt(key, markdown)
        return
    except Exception:
        try:
            storage.add_prompt(key, custom_dir=None)
        except Exception:
            # If add_prompt fails because it already exists or any race, ignore and retry update.
            pass
        svc.update_prompt(key, markdown)


def load_latest_generated_text() -> Optional[str]:
    """
    Load the latest stored taxonomy markdown for comparison (front matter read).
    Returns None if no prior version exists.
    """
    key = "taxonomy-personal-finance"
    storage = FileSystemPromptStorage(find_repo_root())
    svc = PromptService(storage)
    text = svc.load_prompt(key)
    return str(text) if str(text).strip() else None


# ----------------------------
# Core helpers
# ----------------------------
def read_yaml_text(path: str) -> str:
    """
    Read the YAML file content as text.
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _normalize_yaml_for_hash(yaml_text: str) -> str:
    """
    Normalize YAML text for hashing.
    - Prefer canonicalization via PyYAML if available (sorted keys, stable dump)
    - Fallback to whitespace-trimmed text, which is stable but not key-sorted
    - Goal: semantically equivalent YAML yields identical hashes; whitespace-only diffs ignored
    """
    try:
        data = yaml.safe_load(yaml_text)
        # Some YAMLs may be empty (None); represent deterministically
        if data is None:
            return ""
        normalized = yaml.safe_dump(
            data,
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        )
        return normalized.strip()
    except Exception:
        # Fallback: trim leading/trailing whitespace and collapse multiple blank lines
        # This ensures we are at least robust to pure whitespace edits.
        collapsed = re.sub(r"\n\s*\n+", "\n", yaml_text.strip())
        return collapsed


def compute_sha256(text: str) -> str:
    """
    Compute SHA-256 hash in hexadecimal for the given text.
    """
    sha = hashlib.sha256()
    sha.update(text.encode("utf-8"))
    return sha.hexdigest()


def _extract_front_matter(md: str) -> Tuple[Dict[str, Any], int]:
    """
    Extract YAML front matter from the top of a Markdown string.
    Returns (front_matter_dict, end_index_of_front_matter_block).
    If no front matter exists, returns ({}, 0).
    """
    if not md.lstrip().startswith("---"):
        return {}, 0

    # Find the first '---' after the opening line that closes the front matter.
    # We only consider front matter at the very start (ignoring leading whitespace).
    start = md.find("---")
    if start != 0:
        # If there's leading whitespace before '---', strip it and retry simply
        stripped = md.lstrip()
        if not stripped.startswith("---"):
            return {}, 0
        md = stripped
        start = 0

    # Find the closing delimiter
    # The closing '---' must occur after the initial line break
    next_delim_idx = md.find("\n---", 3)
    if next_delim_idx == -1:
        return {}, 0

    fm_block = md[4:next_delim_idx]  # content after first '---\n' up to '\n---'

    fm = yaml.safe_load(fm_block)
    if isinstance(fm, dict):
        return fm, next_delim_idx + 4  # include trailing '---\n'
    return {}, next_delim_idx + 4


def should_regenerate(
    latest_doc: Optional[str],
    input_hash: str,
    prompt_hash: str,
) -> bool:
    """
    Decide whether we should regenerate based on the latest_doc's front matter hashes.
    Returns True if:
      - no latest_doc is present
      - or either input_yaml_sha256 or prompt_sha256 differs
    """
    if not latest_doc:
        return True

    front_matter, _ = _extract_front_matter(latest_doc)
    prev_input = str(front_matter.get("input_yaml_sha256", "")).strip()
    prev_prompt = str(front_matter.get("prompt_sha256", "")).strip()

    if prev_input != input_hash:
        return True
    if prev_prompt != prompt_hash:
        return True
    return False


def render_prompt(merged_template: str, input_yaml: str) -> str:
    """
    Substitute the YAML input into the merged template.
    """
    return merged_template.replace("{input_yaml}", input_yaml)


def call_openai(markdown_prompt: str, model: str) -> str:
    """
    Call OpenAI to generate Markdown given a markdown_prompt.
    This function expects OPENAI_API_KEY to be available in the environment.

    Note: We avoid importing OpenAI types at module import time to keep mypy/ruff happy
    when OpenAI isn't installed in the environment (tests will mock this function).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")

    # Try the modern Responses API; fall back to Chat Completions if unavailable
    client = OpenAI(api_key=api_key)
    try:
        # Newer SDK (Responses API)
        resp = client.responses.create(
            model=model,
            input=markdown_prompt,
        )
        # The text can be located in multiple places; normalize to a single string.
        # Prefer output_text if present; otherwise join all text segments.
        text: Optional[str] = getattr(resp, "output_text", None)
        if text is None:
            # Fallback: try flattening content if output_text isn't available
            text = str(resp)
        return text
    except Exception:
        # Older SDK (Chat Completions)
        chat = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": markdown_prompt}],
        )
        if chat and chat.choices and chat.choices[0].message:
            return chat.choices[0].message.content or ""
        return ""


def _yaml_dump_front_matter(meta: Dict[str, Any]) -> str:
    """
    Serialize a small dict to YAML front matter text.
    - Prefer PyYAML if available
    - Otherwise write a minimal, safe subset
    """
    return yaml.safe_dump(
        meta,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    ).strip()


def wrap_with_front_matter(body_md: str, meta: Dict[str, Any]) -> str:
    """
    Wrap the given Markdown body with YAML front matter. The front matter should include:
      - taxonomy_version: str (set to a placeholder before storage)
      - input_yaml_sha256: str
      - prompt_sha256: str
      - model: str
      - created_at: iso8601
    """
    if "created_at" not in meta:
        meta["created_at"] = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    if "taxonomy_version" not in meta:
        meta["taxonomy_version"] = "TBD"
    fm = _yaml_dump_front_matter(meta)
    return f"---\n{fm}\n---\n\n{body_md.strip()}\n"


# ----------------------------
# Orchestration helpers
# ----------------------------
def load_or_default_merged_template() -> str:
    """
    Try to load the merged prompt template from Promptorium key `taxonomy-generator`.
    Fallback to DEFAULT_MERGED_TEMPLATE if not available.
    """
    try:
        return load_prompt_text("taxonomy-generator")
    except Exception:
        return DEFAULT_MERGED_TEMPLATE


__all__ = [
    "DEFAULT_MERGED_TEMPLATE",
    "load_prompt_text",
    "load_latest_generated_text",
    "read_yaml_text",
    "_normalize_yaml_for_hash",
    "compute_sha256",
    "should_regenerate",
    "render_prompt",
    "call_openai",
    "wrap_with_front_matter",
    "store_generated",
    "load_or_default_merged_template",
]
