"""The sandbox provider seam: create / restore / snapshot / terminate.

A ``Protocol`` so the reaper and lifecycle are testable against a fake, and the
snapshot-vs-`snapshot_filesystem` fallback is isolated behind one interface.
``ModalSandboxProvider`` is the production backend (built here; exercised in the
end-to-end run, not in unit tests, to avoid image-build cycles).
"""

from __future__ import annotations

from typing import Any, Protocol


class SandboxHandle:
    """A live sandbox generation: its id and resolved tunnel URL."""

    def __init__(self, sandbox_id: str, tunnel_url: str) -> None:
        self.sandbox_id = sandbox_id
        self.tunnel_url = tunnel_url


class SandboxProvider(Protocol):
    async def create(self, conversation_id: str) -> SandboxHandle: ...
    async def restore(
        self, conversation_id: str, snapshot_image_id: str
    ) -> SandboxHandle: ...
    async def snapshot(self, sandbox_id: str) -> str: ...  # returns image id; may raise
    async def terminate(self, sandbox_id: str) -> None: ...
    # Live boxes as (sandbox_id, conversation_id) — the reaper's box inventory.
    async def list_active(self) -> list[tuple[str, str]]: ...


class ModalSandboxProvider:
    """Production provider backed by Modal Sandboxes (deploy image + tunnels).

    Isolated so a ``snapshot_directory``→``snapshot_filesystem`` swap is one
    method. Not unit-tested (needs a live image); driven in the final e2e run.
    """

    def __init__(
        self,
        app_name: str,
        image_ref: str,
        *,
        runner_port: int = 8080,
        idle_timeout: int = 3600,
    ) -> None:
        self._app_name = app_name
        self._image_ref = image_ref
        self._runner_port = runner_port
        self._idle_timeout = idle_timeout  # backstop only; Fly's cron reaps at 15m

    async def _new_sandbox(self, image: Any, conversation_id: str) -> SandboxHandle:
        import asyncio

        import httpx
        import modal

        app = await asyncio.to_thread(
            lambda: modal.App.lookup(self._app_name, create_if_missing=True)
        )
        # The sandbox's primary process is the runner server on the tunnel port.
        runner_cmd = [
            "python",
            "-m",
            "uvicorn",
            "runner.server:app",
            "--host",
            "0.0.0.0",  # noqa: S104 - runner binds all interfaces inside its sandbox
            "--port",
            str(self._runner_port),
        ]
        sb = await asyncio.to_thread(
            lambda: modal.Sandbox.create(
                *runner_cmd,
                app=app,
                image=image,
                encrypted_ports=[self._runner_port],
                timeout=self._idle_timeout,
                tags={"conversation_id": conversation_id},
            )
        )
        # Resolve the tunnel, then poll the runner's /healthz until it serves
        # (no readiness probe configured, so we readiness-check ourselves).
        url = None
        for _ in range(30):
            try:
                tunnels = await asyncio.to_thread(lambda: sb.tunnels())
                url = tunnels[self._runner_port].url
                break
            except Exception:  # noqa: BLE001 - tunnel warmup race
                await asyncio.sleep(1)
        if url is None:
            raise RuntimeError("sandbox tunnel never became available")
        async with httpx.AsyncClient(timeout=5.0) as client:
            for _ in range(90):
                try:
                    resp = await client.get(f"{url}/healthz")
                    if resp.status_code == 200:
                        return SandboxHandle(sandbox_id=sb.object_id, tunnel_url=url)
                except Exception:  # noqa: BLE001,S110 - runner still starting; retry loop
                    pass
                await asyncio.sleep(1)
        raise RuntimeError("sandbox runner never became ready")

    async def create(self, conversation_id: str) -> SandboxHandle:
        import modal

        return await self._new_sandbox(
            modal.Image.from_id(self._image_ref), conversation_id
        )

    async def restore(
        self, conversation_id: str, snapshot_image_id: str
    ) -> SandboxHandle:
        import asyncio

        import modal

        # Fresh sandbox from the current base image with the workspace delta mounted.
        handle = await self._new_sandbox(
            modal.Image.from_id(self._image_ref), conversation_id
        )
        sb = await asyncio.to_thread(modal.Sandbox.from_id, handle.sandbox_id)
        await asyncio.to_thread(
            sb.mount_image, "/workspace", modal.Image.from_id(snapshot_image_id)
        )
        return handle

    async def snapshot(self, sandbox_id: str) -> str:
        import asyncio

        import modal

        sb = await asyncio.to_thread(modal.Sandbox.from_id, sandbox_id)
        image = await asyncio.to_thread(sb.snapshot_directory, "/workspace")
        return image.object_id

    async def terminate(self, sandbox_id: str) -> None:
        import asyncio

        import modal

        sb = await asyncio.to_thread(modal.Sandbox.from_id, sandbox_id)
        await asyncio.to_thread(sb.terminate)

    async def list_active(self) -> list[tuple[str, str]]:
        """Live boxes for this app as (sandbox_id, conversation_id) pairs.

        Modal is the durable registry: each box is tagged with its
        ``conversation_id`` at create, so the reaper knows which boxes exist with
        no Fly-side state — it survives a Fly restart. Exited boxes are skipped.
        """
        import asyncio

        import modal

        def _list() -> list[tuple[str, str]]:
            app = modal.App.lookup(self._app_name, create_if_missing=True)
            out: list[tuple[str, str]] = []
            for sb in modal.Sandbox.list(app_id=app.app_id):
                if sb.poll() is not None:  # exited — not a live box
                    continue
                cid = sb.get_tags().get("conversation_id")
                if cid:
                    out.append((sb.object_id, cid))
            return out

        return await asyncio.to_thread(_list)
