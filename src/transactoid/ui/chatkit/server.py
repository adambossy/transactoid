"""ChatKit server exposing Transactoid tools via OpenAI ChatKit SDK."""

from collections.abc import AsyncIterator
import os
from typing import TYPE_CHECKING, Any

from agents import Agent, ModelSettings, Runner
from chatkit.agents import AgentContext, simple_to_agent_input, stream_agent_response
from chatkit.types import ThreadItem, ThreadMetadata, ThreadStreamEvent, UserMessageItem
from dotenv import load_dotenv
from openai.types.shared import Reasoning
from promptorium import load_prompt
import yaml

from transactoid.adapters.clients.plaid import PlaidClient
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.persist.persist_tool import (
    PersistTool,
    RecategorizeTool,
    TagTransactionsTool,
)
from transactoid.tools.query.query_tool import RunSQLTool
from transactoid.tools.registry import ToolRegistry
from transactoid.tools.sync.sync_tool import SyncTransactionsTool
from transactoid.ui.chatkit.adapter import OpenAIAdapter

if TYPE_CHECKING:
    from fastapi import FastAPI

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
        self._categorizer = Categorizer(self._taxonomy)
        self._persist_tool = PersistTool(self._db, self._taxonomy)

        # Create store (required by ChatKitServer)
        store = SimpleInMemoryStore()

        # Initialize ChatKitServer with store
        super().__init__(store)

        # Initialize registry and register tools
        self._registry = ToolRegistry()
        self._register_tools()

        # Create OpenAI adapter (ChatKit uses OpenAI Agents SDK)
        self._adapter = OpenAIAdapter(self._registry)

        # Load instructions
        self._instructions = self._load_instructions()

    def _register_tools(self) -> None:
        """Register all tools with the registry."""
        plaid_client = PlaidClient.from_env()
        plaid_items = self._db.list_plaid_items()

        if plaid_items:
            # Register sync tool (syncs all items automatically)
            sync_tool = SyncTransactionsTool(
                plaid_client=plaid_client,
                categorizer_factory=lambda: self._categorizer,
                db=self._db,
                taxonomy=self._taxonomy,
            )
            self._registry.register(sync_tool)

        # Register persist tools
        recat_tool = RecategorizeTool(self._persist_tool)
        self._registry.register(recat_tool)

        tag_tool = TagTransactionsTool(self._persist_tool)
        self._registry.register(tag_tool)

        # Register query tool
        sql_tool = RunSQLTool(self._db)
        self._registry.register(sql_tool)

    def _load_instructions(self) -> str:
        """Load agent instructions from prompts."""
        # Load prompt template
        template = str(load_prompt("agent-loop"))
        schema_hint = self._db.compact_schema_hint()
        taxonomy_dict = self._taxonomy.to_prompt()

        # Format database schema as readable text
        schema_text = yaml.dump(schema_hint, default_flow_style=False, sort_keys=False)

        # Format taxonomy as readable text
        taxonomy_text = yaml.dump(
            taxonomy_dict, default_flow_style=False, sort_keys=False
        )

        # Load taxonomy rules prompt
        taxonomy_rules = str(load_prompt("taxonomy-rules"))

        # Replace placeholders
        rendered = template.replace("{{DATABASE_SCHEMA}}", schema_text)
        rendered = rendered.replace("{{CATEGORY_TAXONOMY}}", taxonomy_text)
        rendered = rendered.replace("{{TAXONOMY_RULES}}", taxonomy_rules)

        return rendered

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
        # Use OpenAI Agents SDK with adapted tools
        tools = self._adapter.adapt_all()

        agent = Agent(
            name="Transactoid",
            instructions=self._instructions,
            model="gpt-5.1",
            tools=tools,
            model_settings=ModelSettings(
                reasoning=Reasoning(effort="medium"), verbosity="high"
            ),
        )

        # Get the user message text
        if input_user_message is None:
            return

        # Load conversation history from store
        history_page = await self.store.load_thread_items(
            thread.id,
            after=None,
            limit=100,  # Load up to 100 previous items
            order="asc",
            context=context,
        )
        history_items: list[ThreadItem] = history_page.data

        # Add the new user message to history
        history_items.append(input_user_message)

        # Convert thread items to agent input format
        agent_input = await simple_to_agent_input(history_items)

        # Run agent with streaming, passing full conversation history
        result = Runner.run_streamed(
            starting_agent=agent,
            input=agent_input,
        )

        # Create AgentContext for chatkit integration
        agent_context = AgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )

        # Stream agent response using chatkit helper
        async for event in stream_agent_response(agent_context, result):
            yield event


def create_app() -> "FastAPI":
    """Create and configure the FastAPI application."""
    from chatkit.server import StreamingResult
    from fastapi import FastAPI, Request, Response
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
    async def chatkit_endpoint(req: "Request") -> "Response":
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
