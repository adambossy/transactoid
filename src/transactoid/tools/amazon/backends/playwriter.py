"""Playwriter MCP backend for Amazon order scraping."""

from __future__ import annotations

from agents import Agent, Runner
from agents.mcp import MCPServerStdio, MCPServerStdioParams

from transactoid.tools.amazon.scraper import ScrapedOrder, ScrapeResult


class PlaywriterBackend:
    """Amazon scraper backend using Playwriter MCP.

    This backend uses the Playwriter browser extension via MCP to scrape
    Amazon order history. Requires user to have the browser open with
    Playwriter extension activated.
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        """Initialize the Playwriter backend.

        Args:
            model: LLM model to use for the scraper agent. Defaults to gpt-4o.
        """
        self._model = model

    def scrape_order_history(
        self,
        year: int | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history via Playwriter MCP.

        Args:
            year: Optional year to filter orders. If None, scrapes past year.
            max_orders: Optional maximum orders to scrape.

        Returns:
            List of ScrapedOrder objects.
        """
        # Build instructions based on parameters
        year_instruction = f"for year {year}" if year else "for the past year"
        limit_instruction = (
            f"Stop after scraping {max_orders} orders."
            if max_orders
            else "Scrape all available orders."
        )

        instructions = f"""
        Navigate to https://www.amazon.com/your-orders/orders

        Scrape all purchase history {year_instruction}. For each order:
        1. Extract order ID (e.g., "113-5524816-2451403")
        2. Extract order date (YYYY-MM-DD format)
        3. Extract order total, tax, and shipping (convert to cents, $49.77 -> 4977)
        4. For each item: extract ASIN (from URL), description, price (cents), quantity

        Handle pagination - click "Next" to load more orders.
        {limit_instruction}

        Return ALL scraped data as structured JSON matching the output schema.
        """

        # Create Playwriter MCP server
        playwriter_server = MCPServerStdio(
            params=MCPServerStdioParams(command="npx", args=["playwriter"]),
            name="playwriter",
        )

        # Create agent with Playwriter MCP - returns structured JSON
        agent = Agent(
            name="AmazonScraper",
            instructions=instructions,
            model=self._model,
            mcp_servers=[playwriter_server],
            output_type=ScrapeResult,
        )

        # Run scraper agent - returns ScrapeResult
        scrape_result = Runner.run_sync(agent, "Begin scraping Amazon orders")

        final_output = scrape_result.final_output
        if final_output is None:
            return []

        return list(final_output.orders)
