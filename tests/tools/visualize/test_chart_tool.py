"""Unit tests for GenerateChartTool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from transactoid.tools.visualize.chart_tool import (
    GenerateChartTool,
    _generate_ascii_plot,
    pop_chart_path,
)


def create_chart_tool() -> GenerateChartTool:
    return GenerateChartTool()


def test_generate_chart_bar_returns_success():
    # input
    input_data = {
        "chart_type": "bar",
        "title": "Spending by Category",
        "data": {"Groceries": 450.0, "Dining": 200.0, "Transport": 150.0},
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))

    # assert
    assert output["status"] == "success"
    assert "html_img_tag" not in output
    assert "file_path" not in output
    pop_chart_path("Spending by Category")  # consume to avoid registry leak


def test_generate_chart_line_returns_success():
    # input
    input_data = {
        "chart_type": "line",
        "title": "Monthly Spending",
        "data": {"Jan": 1200.0, "Feb": 980.0, "Mar": 1350.0},
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))

    # assert
    assert output["status"] == "success"
    assert "html_img_tag" not in output
    assert "file_path" not in output
    pop_chart_path("Monthly Spending")  # consume to avoid registry leak


def test_generate_chart_pie_returns_success():
    # input
    input_data = {
        "chart_type": "pie",
        "title": "Expense Breakdown",
        "data": {"Housing": 2000.0, "Food": 600.0, "Entertainment": 300.0},
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))

    # assert
    assert output["status"] == "success"
    assert "html_img_tag" not in output
    assert "file_path" not in output
    assert output["ascii_plot"] is None
    pop_chart_path("Expense Breakdown")  # consume to avoid registry leak


def test_generate_chart_saves_png_file():
    # input
    input_data = {
        "chart_type": "bar",
        "title": "File Save Test",
        "data": {"A": 100.0, "B": 200.0},
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))
    file_path = pop_chart_path("File Save Test")

    # assert
    assert output["status"] == "success"
    assert file_path is not None
    assert Path(file_path).exists()


def test_generate_chart_invalid_data_type():
    # input
    input_data = {
        "chart_type": "bar",
        "title": "Bad Data",
        "data": "not a dict",
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))

    # assert
    assert output["status"] == "error"
    assert "error" in output


def test_generate_chart_empty_data():
    # input
    input_data = {
        "chart_type": "bar",
        "title": "Empty Data",
        "data": {},
    }

    # act
    tool = create_chart_tool()
    output = asyncio.run(tool.execute(**input_data))

    # assert
    assert output["status"] == "error"
    assert "error" in output


def test_generate_ascii_plot_returns_none_for_pie():
    # input
    labels = ["Housing", "Food", "Entertainment"]
    values = [2000.0, 600.0, 300.0]

    # act
    output = _generate_ascii_plot("pie", labels, values, "Expense Breakdown")

    # assert
    assert output is None


def test_generate_ascii_plot_returns_none_when_gnuplot_missing():
    # input
    labels = ["Groceries", "Dining"]
    values = [450.0, 200.0]

    # act
    with patch(
        "transactoid.tools.visualize.chart_tool.subprocess.run",
        side_effect=FileNotFoundError("gnuplot not found"),
    ):
        output = _generate_ascii_plot("bar", labels, values, "Test Chart")

    # assert
    assert output is None
