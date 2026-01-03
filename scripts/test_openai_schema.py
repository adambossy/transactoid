#!/usr/bin/env python3
"""Test script to verify OpenAI Responses API schema is valid.

Usage:
    uv run python scripts/test_openai_schema.py
"""

import asyncio
import json
import os

from openai import AsyncOpenAI


def build_response_schema(valid_keys: list[str]) -> dict[str, object]:
    """Build JSON schema for OpenAI Responses API text.format parameter.

    This is a copy of Categorizer._build_response_schema for testing.
    """
    return {
        "type": "json_schema",
        "name": "categorization",
        "schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "idx": {"type": "integer"},
                            "category": {"type": "string", "enum": valid_keys},
                            "score": {"type": "number"},
                            "rationale": {"type": "string"},
                            "revised_category": {
                                "anyOf": [
                                    {"type": "null"},
                                    {"type": "string", "enum": valid_keys},
                                ]
                            },
                            "revised_score": {"type": ["number", "null"]},
                            "revised_rationale": {"type": ["string", "null"]},
                            "merchant_summary": {"type": ["string", "null"]},
                            "citations": {
                                "anyOf": [
                                    {"type": "null"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
                            },
                        },
                        "required": [
                            "idx",
                            "category",
                            "score",
                            "rationale",
                            "revised_category",
                            "revised_score",
                            "revised_rationale",
                            "merchant_summary",
                            "citations",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["results"],
            "additionalProperties": False,
        },
        "strict": True,
    }


async def test_schema() -> None:
    """Test the schema with a simple API call."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        return

    client = AsyncOpenAI(api_key=api_key)

    # Sample category keys
    valid_keys = [
        "food.groceries",
        "food.restaurants",
        "shopping.general",
        "income.salary",
    ]

    # Build the schema
    schema = build_response_schema(valid_keys)
    print("Schema to be sent:")
    print(json.dumps(schema, indent=2))
    print()

    # Simple test prompt
    prompt = """Categorize this transaction:

{"idx": 0, "description": "WHOLE FOODS", "merchant": "Whole Foods", "amount": 45.67}

Return JSON with a "results" array containing one object with the categorization.
Valid categories: food.groceries, food.restaurants, shopping.general, income.salary
"""

    print("Sending test request to OpenAI Responses API...")
    print()

    try:
        resp = await client.responses.create(
            model="gpt-4o-mini",  # Use cheaper model for testing
            input=prompt,
            extra_body={"text": {"format": schema}},
        )

        response_text = getattr(resp, "output_text", str(resp))
        print("SUCCESS! Response received:")
        print(response_text)
        print()

        # Try to parse the response
        data = json.loads(response_text)
        if "results" in data:
            print(f"Parsed {len(data['results'])} result(s)")
            for result in data["results"]:
                idx, cat, score = result["idx"], result["category"], result["score"]
                print(f"  - idx={idx}, category={cat}, score={score}")
        else:
            print("WARNING: Response doesn't have 'results' key")
            print(f"Keys found: {list(data.keys())}")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(test_schema())
