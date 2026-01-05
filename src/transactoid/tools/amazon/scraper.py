"""Amazon order scraper using Playwriter MCP for browser automation."""

from __future__ import annotations

from datetime import date
from typing import Any

from agents import Agent, Runner
from agents.mcp import MCPServerStdio, MCPServerStdioParams
from pydantic import BaseModel

from transactoid.adapters.db.facade import DB


class ScrapedItem(BaseModel):
    """A single item scraped from an Amazon order."""

    asin: str
    description: str
    price_cents: int
    quantity: int


class ScrapedOrder(BaseModel):
    """A single Amazon order scraped from order history."""

    order_id: str
    order_date: str  # YYYY-MM-DD format
    order_total_cents: int
    tax_cents: int
    shipping_cents: int
    items: list[ScrapedItem]


class ScrapeResult(BaseModel):
    """Result of scraping Amazon orders."""

    orders: list[ScrapedOrder]


def scrape_with_playwriter(db: DB) -> dict[str, Any]:
    """Execute Playwriter-powered scraping via OpenAI, then upsert results.

    This function:
    1. Creates an agent with Playwriter MCP access
    2. Instructs the agent to navigate Amazon and scrape order history
    3. Receives structured JSON from the agent
    4. Upserts all orders and items to the database

    Args:
        db: Database facade for persisting scraped data

    Returns:
        Dictionary with status and summary of scraped data
    """
    instructions = """
    Navigate to https://www.amazon.com/your-orders/orders

    Scrape all purchase history for the past year. For each order:
    1. Extract order ID (e.g., "113-5524816-2451403")
    2. Extract order date (YYYY-MM-DD format)
    3. Extract order total, tax, and shipping (convert to cents, $49.77 -> 4977)
    4. For each item: extract ASIN (from URL), description, price (cents), quantity

    Handle pagination - click "Next" to load more orders until you've
    scraped a full year of history.

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
        model="gpt-4o",
        mcp_servers=[playwriter_server],
        output_type=ScrapeResult,
    )

    # Run scraper agent - returns ScrapeResult
    scrape_result = Runner.run_sync(agent, "Begin scraping Amazon orders")

    # Deterministic code: upsert results to database
    orders_created = 0
    items_created = 0

    final_output = scrape_result.final_output
    if final_output is None:
        return {
            "status": "error",
            "message": "Scraper did not return any results",
            "orders_created": 0,
            "items_created": 0,
        }

    for order in final_output.orders:
        db.upsert_amazon_order(
            order_id=order.order_id,
            order_date=date.fromisoformat(order.order_date),
            order_total_cents=order.order_total_cents,
            tax_cents=order.tax_cents,
            shipping_cents=order.shipping_cents,
        )
        orders_created += 1

        for item in order.items:
            db.upsert_amazon_item(
                order_id=order.order_id,
                asin=item.asin,
                description=item.description,
                price_cents=item.price_cents,
                quantity=item.quantity,
            )
            items_created += 1

    return {
        "status": "success",
        "orders_created": orders_created,
        "items_created": items_created,
    }
