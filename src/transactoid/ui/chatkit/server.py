"""ChatKit server exposing Transactoid tools via OpenAI ChatKit SDK."""

import base64
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageContentPartTextDelta,
    AssistantMessageItem,
    GeneratedImage,
    GeneratedImageItem,
    ThreadItemAddedEvent,
    ThreadItemDoneEvent,
    ThreadItemUpdatedEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
)
from dotenv import load_dotenv
from fastapi import Request, Response

from transactoid.adapters.db.facade import DB
from transactoid.core.runtime import (
    CoreSession,
    TextDeltaEvent,
    ToolCallOutputEvent,
    ToolCallStartedEvent,
)
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.loader import load_taxonomy_from_db

if TYPE_CHECKING:

    class _ChatKitServerBase:
        store: Any

        def __init__(self, store: Any) -> None: ...

        async def process(self, body: bytes, context: Any) -> Any: ...

else:
    from chatkit.server import ChatKitServer as _ChatKitServerBase


class TransactoidChatKitServer(_ChatKitServerBase):
    """ChatKit server exposing Transactoid tools."""

    def __init__(self) -> None:
        """Initialize the ChatKit server with services and tools."""
        # Import store here to avoid circular imports
        from transactoid.ui.simple_store import SimpleInMemoryStore

        # Initialize services
        db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        self._db = DB(db_url)
        self._taxonomy = load_taxonomy_from_db(self._db)
        self._transactoid = Transactoid(db=self._db, taxonomy=self._taxonomy)
        self._runtime = self._transactoid.create_runtime()
        self._runtime_sessions: dict[str, CoreSession] = {}
        self._pending_tool_calls: dict[str, str] = {}

        # Create store (required by ChatKitServer)
        store = SimpleInMemoryStore()

        # Initialize ChatKitServer with store
        super().__init__(store)

    async def respond(
        self,
        thread: ThreadMetadata,
        input_user_message: UserMessageItem | None,
        context: Any,
    ) -> AsyncIterator[ThreadStreamEvent]:
        """
        ChatKit respond method - handles each user message.

        Args:
            thread: Thread metadata
            input_user_message: User message input
            context: Request context

        Yields:
            Thread stream events for ChatKit
        """
        if input_user_message is None:
            return

        user_text = self._extract_user_text(input_user_message)
        if not user_text:
            return

        runtime_session = self._runtime_sessions.get(thread.id)
        if runtime_session is None:
            runtime_session = self._runtime.start_session(thread.id)
            self._runtime_sessions[thread.id] = runtime_session

        assistant_message = AssistantMessageItem(
            id=self.store.generate_item_id("message", thread, context),
            thread_id=thread.id,
            created_at=datetime.now(),
            content=[AssistantMessageContent(text="", annotations=[])],
        )
        yield ThreadItemAddedEvent(item=assistant_message)

        async for runtime_event in self._runtime.run_streamed(
            input_text=user_text,
            session=runtime_session,
        ):
            if isinstance(runtime_event, TextDeltaEvent):
                assistant_message.content[0].text += runtime_event.text
                yield ThreadItemUpdatedEvent(
                    item_id=assistant_message.id,
                    update=AssistantMessageContentPartTextDelta(
                        content_index=0,
                        delta=runtime_event.text,
                    ),
                )
            elif isinstance(runtime_event, ToolCallStartedEvent):
                self._pending_tool_calls[runtime_event.call_id] = (
                    runtime_event.tool_name
                )
            elif isinstance(runtime_event, ToolCallOutputEvent):
                tool_name = self._pending_tool_calls.pop(runtime_event.call_id, None)
                if (
                    tool_name == "generate_chart"
                    and isinstance(runtime_event.output, dict)
                    and runtime_event.status == "completed"
                ):
                    file_path = runtime_event.output.get("file_path", "")
                    if isinstance(file_path, str) and file_path:
                        for event in _emit_chart_image(
                            file_path,
                            runtime_event.call_id,
                            thread,
                            self.store,
                            context,
                        ):
                            yield event

        yield ThreadItemDoneEvent(item=assistant_message)

    def _extract_user_text(self, user_message: UserMessageItem) -> str:
        for content in user_message.content:
            if content.type == "input_text":
                text_value = content.text
                if isinstance(text_value, str):
                    return text_value
        return ""


def _emit_chart_image(
    file_path: str,
    call_id: str,
    thread: ThreadMetadata,
    store: Any,
    context: Any,
) -> Iterator[ThreadStreamEvent]:
    """Read PNG at file_path, convert to data URL, yield GeneratedImageItem events."""
    try:
        b64 = base64.b64encode(Path(file_path).read_bytes()).decode("ascii")
    except OSError:
        return

    data_url = f"data:image/png;base64,{b64}"
    image_item = GeneratedImageItem(
        id=store.generate_item_id("image", thread, context),
        thread_id=thread.id,
        created_at=datetime.now(),
        image=GeneratedImage(id=call_id, url=data_url),
    )
    yield ThreadItemAddedEvent(item=image_item)
    yield ThreadItemDoneEvent(item=image_item)


def create_app() -> Any:
    """Create and configure the FastAPI application."""
    from chatkit.server import StreamingResult
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse

    # Load environment variables
    load_dotenv(override=False)

    # Create server instance
    server = TransactoidChatKitServer()

    # Create FastAPI app
    app = FastAPI()

    # Add CORS middleware for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/debug")
    async def debug_routes() -> dict[str, list[str]]:
        """List all registered routes."""
        routes = [
            getattr(route, "path", route.__class__.__name__) for route in app.routes
        ]
        return {"routes": routes}

    @app.post("/chatkit")
    async def chatkit_endpoint(req: Request) -> Response:
        """ChatKit endpoint that processes requests."""
        body = await req.body()
        print(f"Request method: {req.method}")
        print(f"Request headers: {dict(req.headers)}")
        print(f"Request body: {body[:500]!r}" if body else "Request body: empty")

        if not body:
            return Response(
                content='{"error": "No request body"}',
                media_type="application/json",
                status_code=400,
            )

        result = await server.process(body, context={})
        if isinstance(result, StreamingResult):
            return StreamingResponse(result, media_type="text/event-stream")
        return Response(content=result.json, media_type="application/json")

    return app


def main() -> None:
    """Main entry point for ChatKit server."""
    import uvicorn

    uvicorn.run(
        "transactoid.ui.chatkit.server:create_app",
        host="0.0.0.0",  # noqa: S104
        port=8000,
        reload=True,
        factory=True,
    )


if __name__ == "__main__":
    main()
