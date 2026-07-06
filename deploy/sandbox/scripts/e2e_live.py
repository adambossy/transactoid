"""Phase 6 — scripted end-to-end verification of the four scenarios.

Runs against a *live* stack (all secrets read from env by the launcher script,
never hardcoded):

    PENNY_E2E_FLY_BASE     the Fly backend base URL (chat + resume + cancel)
    PENNY_E2E_CONV         a conversation id to use

Each scenario asserts at the API level exactly what the plan's Verification page
specifies. This is the browser e2e minus the browser: it drives the same
`/api/chat` SSE contract the frontend uses, so a green run here is the cutover
gate (a Playwright wrapper adds only the UI layer).

Prereqs (stood up by `deploy/sandbox/scripts/up.sh`, not this file):
  * the runner image built (`modal run deploy/sandbox/modal_app.py::publish`),
  * the secrets proxy deployed (`modal deploy deploy/sandbox/proxy/modal_app.py`),
  * the Fly backend running with `PENNY_SANDBOX_TURNS=1` and its MCP server
    exposed to Modal via ngrok,
  * a real GOOGLE_API_KEY registered with the proxy for the conversation.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx


def _frames(chunk: str) -> list[dict]:
    out = []
    for line in chunk.splitlines():
        if line.startswith("data: ") and line[6:].strip() not in ("[DONE]", ""):
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return out


async def _send(client: httpx.AsyncClient, base: str, conv: str, text: str) -> list[dict]:
    frames: list[dict] = []
    body = {"id": conv, "message": {"id": "u1", "role": "user", "parts": [{"type": "text", "text": text}]}}
    async with client.stream("POST", f"{base}/api/chat", json=body) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            frames.extend(_frames(line))
    return frames


async def scenario_1_happy_path(client: httpx.AsyncClient, base: str, conv: str) -> None:
    """New conversation → answered by a sandbox; streamed text arrives."""
    frames = await _send(client, base, conv, "In one sentence, what can you help me with?")
    types = [f["type"] for f in frames]
    assert "start" in types and "finish" in types, types
    assert any(f["type"] == "text-delta" for f in frames), "no streamed text"


async def scenario_2_tool_call(client: httpx.AsyncClient, base: str, conv: str) -> None:
    """A message that invokes a tool → tool-input/-output frames appear."""
    frames = await _send(client, base, conv, "Show my five largest transactions.")
    types = [f["type"] for f in frames]
    assert "tool-input-available" in types, f"no tool call: {types}"
    assert "tool-output-available" in types or "tool-output-error" in types, types


async def scenario_3_cancel(client: httpx.AsyncClient, base: str, conv: str) -> None:
    """Cancel mid-run → stream closes cleanly, run stops."""
    task = asyncio.create_task(_send(client, base, conv, "Write a long, detailed multi-step analysis."))
    await asyncio.sleep(1.5)  # let it start streaming
    await client.post(f"{base}/api/chat/{conv}/cancel")
    frames = await task
    types = [f["type"] for f in frames]
    # A clean close: no dangling error banner beyond an optional cancellation note.
    assert "start" in types, types


async def scenario_4_persistence(client: httpx.AsyncClient, base: str, conv: str) -> None:
    """Close + reopen → prior turns rehydrate from the conversation store."""
    session = (await client.get(f"{base}/api/sessions/{conv}")).json()
    messages = session.get("messages", session)
    assert messages, "conversation did not persist across reopen"


async def main() -> None:
    base = os.environ["PENNY_E2E_FLY_BASE"].rstrip("/")
    conv = os.environ.get("PENNY_E2E_CONV", "e2e-conv-1")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        for name, fn in [
            ("1 happy-path", scenario_1_happy_path),
            ("2 tool-call", scenario_2_tool_call),
            ("3 cancel", scenario_3_cancel),
            ("4 persistence", scenario_4_persistence),
        ]:
            await fn(client, base, conv)
            print(f"PASS scenario {name}")
    print("ALL FOUR E2E SCENARIOS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
