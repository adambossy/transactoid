"""Chart generation tool — produces PNG file and ASCII plot."""

from __future__ import annotations

from datetime import datetime
import io
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import uuid

# isort: off
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# isort: on

from transactoid.tools.base import StandardTool
from transactoid.tools.protocol import ToolInputSchema

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")

# Maps chart title → saved file path. Populated by _execute_impl and consumed
# by the ChatKit server to emit an inline image without exposing the local path
# to the LLM (which would embed it as a broken markdown image reference).
_pending_chart_paths: dict[str, str] = {}


def pop_chart_path(title: str) -> str | None:
    """Pop and return the saved PNG path for a pending chart, or None."""
    return _pending_chart_paths.pop(title, None)


CHART_COLORS = [
    "#2563eb",
    "#16a34a",
    "#ca8a04",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#9333ea",
]


def _generate_ascii_plot(
    chart_type: str,
    labels: list[str],
    values: list[float],
    title: str,
) -> str | None:
    """Generate an ASCII plot via gnuplot.

    Returns None for pie charts, when gnuplot is not installed, or on error.
    """
    if chart_type == "pie":
        return None

    # Build inline data: integer x positions paired with values
    data_lines = "\n".join(f"{idx + 1} {value}" for idx, value in enumerate(values))
    xtics = ", ".join(f'"{label}" {idx + 1}' for idx, label in enumerate(labels))

    if chart_type == "bar":
        plot_cmd = 'set style fill solid; plot "-" using 1:2 with boxes title ""'
    else:
        plot_cmd = 'plot "-" using 1:2 with linespoints title ""'

    script = (
        f"set terminal dumb 80 25\n"
        f"set title '{title}'\n"
        f"set xtics ({xtics})\n"
        f"{plot_cmd}\n"
        f"{data_lines}\n"
        f"e\n"
    )

    try:
        result = subprocess.run(
            ["gnuplot"],  # noqa: S607
            input=script,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


class GenerateChartTool(StandardTool):
    """Generate a chart and save it as a PNG file."""

    _name = "generate_chart"
    _description = (
        "Generate a chart from labeled data. The image is displayed automatically "
        "in the chat — do not reference any file path in your response. "
        "Returns title and ascii_plot (when gnuplot is available) for terminal display."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "pie"],
                "description": "Type of chart to generate",
            },
            "title": {
                "type": "string",
                "description": "Chart title",
            },
            "data": {
                "type": "string",
                "description": (
                    "JSON-encoded label-to-number mapping, "
                    "e.g. '{\"Groceries\": 450.0}'"
                ),
            },
            "x_label": {
                "type": "string",
                "description": "Optional x-axis label (empty string if not needed)",
            },
            "y_label": {
                "type": "string",
                "description": "Optional y-axis label (empty string if not needed)",
            },
        },
        "required": ["chart_type", "title", "data", "x_label", "y_label"],
    }

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        chart_type = str(kwargs.get("chart_type", ""))
        title = str(kwargs.get("title", ""))
        raw_data: Any = kwargs.get("data", {})
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "error": f"data must be valid JSON; got {raw_data!r}",
                }
        data: dict[str, Any] = raw_data
        x_label = str(kwargs.get("x_label", ""))
        y_label = str(kwargs.get("y_label", ""))

        if not isinstance(data, dict):
            return {
                "status": "error",
                "error": (
                    "data must be a dict mapping labels to numbers; "
                    f"got {type(data).__name__}"
                ),
            }
        if not data:
            return {
                "status": "error",
                "error": "data must not be empty",
            }

        # Coerce values to float
        labels: list[str] = []
        values: list[float] = []
        for label, raw_value in data.items():
            try:
                values.append(float(raw_value))
            except (TypeError, ValueError):
                return {
                    "status": "error",
                    "error": (
                        f"Could not convert value for '{label}' to float: {raw_value!r}"
                    ),
                }
            labels.append(str(label))

        # Sort chronologically when all labels are ISO date strings (YYYY-MM or
        # YYYY-MM-DD). Lexicographic order equals chronological order for these
        # formats, so no date parsing is required.
        if all(_ISO_DATE_RE.match(lbl) for lbl in labels):
            pairs = sorted(zip(labels, values), key=lambda pair: pair[0])
            labels = [pair[0] for pair in pairs]
            values = [pair[1] for pair in pairs]

        # Build figure
        figsize = (8, 8) if chart_type == "pie" else (10, 6)
        fig, ax = plt.subplots(figsize=figsize)

        num_items = len(labels)
        colors = (CHART_COLORS * ((num_items // len(CHART_COLORS)) + 1))[:num_items]

        if chart_type == "bar":
            ax.bar(labels, values, color=colors)
            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)
            plt.xticks(rotation=45, ha="right")
        elif chart_type == "line":
            ax.plot(labels, values, color=CHART_COLORS[0], marker="o")
            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)
            plt.xticks(rotation=45, ha="right")
        elif chart_type == "pie":
            ax.pie(values, labels=labels, colors=colors, autopct="%1.1f%%")
            ax.axis("equal")
        else:
            plt.close(fig)
            return {
                "status": "error",
                "error": f"Unsupported chart_type: {chart_type!r}",
            }

        ax.set_title(title, fontsize=14, fontweight="bold")
        plt.tight_layout()

        # Render to PNG in memory
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        png_bytes = buf.read()

        # Save PNG file
        charts_dir = Path(".cache/charts").resolve()
        charts_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex
        filename = f"{timestamp}-{uid[:8]}-{chart_type}.png"
        file_path = charts_dir / filename
        file_path.write_bytes(png_bytes)

        ascii_plot = _generate_ascii_plot(chart_type, labels, values, title)

        # Register the path for the ChatKit server to consume; do not return it
        # to the LLM (it would embed it as a broken markdown image reference).
        _pending_chart_paths[title] = str(file_path)

        return {
            "status": "success",
            "title": title,
            "ascii_plot": ascii_plot,
        }
