"""HTML renderer for spending reports using GPT-5.2."""

from __future__ import annotations

import os

from openai import OpenAI

from transactoid.prompts.loader import load_transactoid_prompt


def render_report_html(markdown_text: str) -> str:
    """Convert a markdown spending report to styled HTML using GPT-5.2.

    Args:
        markdown_text: The markdown report content

    Returns:
        Styled HTML document
    """
    # Load prompt template from promptorium
    prompt_template = load_transactoid_prompt("render-report-html")

    # Inject the markdown report into the prompt
    prompt = prompt_template.replace("{{MARKDOWN_REPORT}}", markdown_text)

    # Call GPT-5.2 to render the HTML
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-5.2",
        input=prompt,
    )

    html_content: str = response.output_text
    return html_content
