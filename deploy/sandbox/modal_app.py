"""Modal image bake for the sandbox runner (deploy artifact).

Builds the thin runner image: agent-harness (from its pinned git commit — the
package isn't on PyPI) plus a web server, and the `sandbox/` source (runner +
protocol) vendored in. Deliberately NO finance stack — tools run on Fly over
MCP. The runner is the image's entrypoint, serving on the tunnel port.

Build/publish the image id with:
    modal run deploy/sandbox/modal_app.py::publish
which prints the image id the backend passes to ``ModalSandboxProvider``.
"""

from __future__ import annotations

from pathlib import Path

import modal

# The runner source (this repo's `sandbox/` package) and the shared wire
# protocol (the `protocol` package from the `lib/` workspace member).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_SRC = str(_REPO_ROOT / "sandbox")
_PROTOCOL_SRC = str(_REPO_ROOT / "lib" / "protocol")
_HARNESS = (
    "agent-harness[mcp,google] @ "
    "git+https://github.com/adambossy/agent-harness.git@47228dd085202424157f0ffb65c2114c250b7d48"
)
RUNNER_PORT = 8080

app = modal.App("penny-sandbox")

image = (
    # agent-harness requires Python >=3.13.
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git", "ripgrep")
    # Pin pydantic-graph/pydantic to the backend's known-good resolution — a
    # looser resolve pulled a pydantic-graph that dropped ``GraphRunResult`` and
    # crashed the runner on import.
    .pip_install(
        _HARNESS,
        "pydantic-graph==1.103.0",
        "pydantic==2.13.4",
        "fastapi>=0.115",
        "uvicorn>=0.30",
        "mcp>=1.0",
        "httpx>=0.27",
    )
    # Vendor the runner + protocol packages at /app (copy=True bakes a layer).
    .add_local_dir(_SANDBOX_SRC, remote_path="/app", copy=True, ignore=["tests", "*.md", "**/__pycache__"])
    .add_local_dir(_PROTOCOL_SRC, remote_path="/app/protocol", copy=True, ignore=["**/__pycache__"])
    .workdir("/app")
    .env({"PYTHONPATH": "/app"})
)

# The command the sandbox's primary process runs: the runner server on the port.
RUNNER_CMD = ["python", "-m", "uvicorn", "runner.server:app", "--host", "0.0.0.0", "--port", str(RUNNER_PORT)]


@app.local_entrypoint()
def publish() -> None:
    """Build/hydrate the image and print its id (``PENNY_SANDBOX_IMAGE``)."""
    sb = modal.Sandbox.create("true", app=app, image=image, timeout=60)
    try:
        print(f"IMAGE_ID={image.object_id}")
    finally:
        sb.terminate()


@app.local_entrypoint()
def smoke() -> None:
    """Live infra proof: build the image, create a sandbox running the runner,
    resolve its tunnel, confirm ``/healthz``, then tear it down.
    """
    import time

    import httpx

    sb = modal.Sandbox.create(
        *RUNNER_CMD, app=app, image=image, encrypted_ports=[RUNNER_PORT], timeout=600
    )
    try:
        url = sb.tunnels()[RUNNER_PORT].url
        print(f"sandbox {sb.object_id} tunnel {url}")
        ready = False
        for _ in range(60):  # poll the tunnel until the runner answers
            try:
                resp = httpx.get(f"{url}/healthz", timeout=5)
                if resp.status_code == 200 and resp.json().get("status") == "ok":
                    print(f"healthz -> {resp.status_code} {resp.text}")
                    ready = True
                    break
            except Exception:  # noqa: BLE001 - tunnel/warmup races
                pass
            time.sleep(2)
        assert ready, "runner never became ready"
        print("LIVE SMOKE OK: Modal sandbox + tunnel + runner server verified")
    finally:
        sb.terminate()
