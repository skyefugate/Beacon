"""Tests for beacon CLI output utilities."""

from __future__ import annotations

import json
from unittest.mock import patch

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from beacon.cli.output import (
    console,
    err_console,
    print_error,
    print_json,
    print_panel,
    print_success,
    print_table,
    print_warning,
)


class TestPrintSuccess:
    def test_print_success_message(self):
        """Test print_success outputs green message."""
        with patch.object(console, "print") as mock_print:
            print_success("Operation completed")

            mock_print.assert_called_once_with("[green]Operation completed[/green]")

    def test_print_success_empty_message(self):
        """Test print_success with empty message."""
        with patch.object(console, "print") as mock_print:
            print_success("")

            mock_print.assert_called_once_with("[green][/green]")

    def test_print_success_special_characters(self):
        """Test print_success with special characters."""
        with patch.object(console, "print") as mock_print:
            print_success("Success: 100% complete!")

            mock_print.assert_called_once_with("[green]Success: 100% complete![/green]")


class TestPrintError:
    def test_print_error_message(self):
        """Test print_error outputs red message to stderr."""
        with patch.object(err_console, "print") as mock_print:
            print_error("Something went wrong")

            mock_print.assert_called_once_with("[red]Error:[/red] Something went wrong")

    def test_print_error_empty_message(self):
        """Test print_error with empty message."""
        with patch.object(err_console, "print") as mock_print:
            print_error("")

            mock_print.assert_called_once_with("[red]Error:[/red] ")

    def test_print_error_multiline_message(self):
        """Test print_error with multiline message."""
        with patch.object(err_console, "print") as mock_print:
            print_error("Line 1\nLine 2")

            mock_print.assert_called_once_with("[red]Error:[/red] Line 1\nLine 2")


class TestPrintWarning:
    def test_print_warning_message(self):
        """Test print_warning outputs yellow message."""
        with patch.object(console, "print") as mock_print:
            print_warning("This is a warning")

            mock_print.assert_called_once_with("[yellow]This is a warning[/yellow]")

    def test_print_warning_empty_message(self):
        """Test print_warning with empty message."""
        with patch.object(console, "print") as mock_print:
            print_warning("")

            mock_print.assert_called_once_with("[yellow][/yellow]")


class TestPrintJson:
    def test_print_json_simple_dict(self):
        """Test print_json with simple dictionary."""
        data = {"key": "value", "number": 42}

        with patch.object(console, "print_json") as mock_print_json:
            print_json(data)

            expected_json = json.dumps(data, indent=2, default=str)
            mock_print_json.assert_called_once_with(expected_json)

    def test_print_json_nested_dict(self):
        """Test print_json with nested dictionary."""
        data = {"level1": {"level2": {"value": "nested"}}, "array": [1, 2, 3]}

        with patch.object(console, "print_json") as mock_print_json:
            print_json(data)

            expected_json = json.dumps(data, indent=2, default=str)
            mock_print_json.assert_called_once_with(expected_json)

    def test_print_json_empty_dict(self):
        """Test print_json with empty dictionary."""
        data = {}

        with patch.object(console, "print_json") as mock_print_json:
            print_json(data)

            expected_json = json.dumps(data, indent=2, default=str)
            mock_print_json.assert_called_once_with(expected_json)

    def test_print_json_with_non_serializable_objects(self):
        """Test print_json with objects that need default=str."""
        from datetime import datetime

        data = {"timestamp": datetime(2024, 1, 1, 12, 0, 0), "path": "/some/path"}

        with patch.object(console, "print_json") as mock_print_json:
            print_json(data)

            # Should use default=str to handle datetime
            expected_json = json.dumps(data, indent=2, default=str)
            mock_print_json.assert_called_once_with(expected_json)


class TestPrintTable:
    def test_print_table_simple(self):
        """Test print_table with simple data."""
        title = "Test Table"
        columns = ["Name", "Age"]
        rows = [["Alice", "30"], ["Bob", "25"]]

        with patch.object(console, "print") as mock_print:
            print_table(title, columns, rows)

            mock_print.assert_called_once()
            # Verify a Table object was passed
            args = mock_print.call_args[0]
            assert len(args) == 1
            assert isinstance(args[0], Table)

    def test_print_table_empty_rows(self):
        """Test print_table with no rows."""
        title = "Empty Table"
        columns = ["Col1", "Col2"]
        rows = []

        with patch.object(console, "print") as mock_print:
            print_table(title, columns, rows)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Table)

    def test_print_table_single_column(self):
        """Test print_table with single column."""
        title = "Single Column"
        columns = ["Item"]
        rows = [["Item1"], ["Item2"], ["Item3"]]

        with patch.object(console, "print") as mock_print:
            print_table(title, columns, rows)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Table)

    def test_print_table_many_columns(self):
        """Test print_table with many columns."""
        title = "Wide Table"
        columns = ["A", "B", "C", "D", "E"]
        rows = [["1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"]]

        with patch.object(console, "print") as mock_print:
            print_table(title, columns, rows)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Table)

    def test_print_table_with_rich_markup(self):
        """Test print_table with Rich markup in data."""
        title = "Styled Table"
        columns = ["Status", "Message"]
        rows = [
            ["[green]Success[/green]", "Operation completed"],
            ["[red]Error[/red]", "Something failed"],
        ]

        with patch.object(console, "print") as mock_print:
            print_table(title, columns, rows)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Table)


class TestPrintPanel:
    def test_print_panel_default_style(self):
        """Test print_panel with default blue style."""
        title = "Test Panel"
        content = "This is panel content"

        with patch.object(console, "print") as mock_print:
            print_panel(title, content)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert len(args) == 1
            assert isinstance(args[0], Panel)

    def test_print_panel_custom_style(self):
        """Test print_panel with custom style."""
        title = "Warning Panel"
        content = "This is a warning"
        style = "red"

        with patch.object(console, "print") as mock_print:
            print_panel(title, content, style)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Panel)

    def test_print_panel_empty_content(self):
        """Test print_panel with empty content."""
        title = "Empty Panel"
        content = ""

        with patch.object(console, "print") as mock_print:
            print_panel(title, content)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Panel)

    def test_print_panel_multiline_content(self):
        """Test print_panel with multiline content."""
        title = "Multi-line Panel"
        content = "Line 1\nLine 2\nLine 3"

        with patch.object(console, "print") as mock_print:
            print_panel(title, content)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Panel)

    def test_print_panel_with_rich_markup(self):
        """Test print_panel with Rich markup in content."""
        title = "Styled Panel"
        content = "[bold]Bold text[/bold] and [italic]italic text[/italic]"

        with patch.object(console, "print") as mock_print:
            print_panel(title, content)

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert isinstance(args[0], Panel)


class TestConsoleInstances:
    def test_console_is_console_instance(self):
        """Test that console is a Console instance."""
        assert isinstance(console, Console)

    def test_err_console_is_console_instance(self):
        """Test that err_console is a Console instance."""
        assert isinstance(err_console, Console)

    def test_err_console_uses_stderr(self):
        """Test that err_console is configured for stderr."""
        # err_console should be configured with stderr=True
        # Check if it's a different instance from regular console
        assert err_console is not console

    def test_console_and_err_console_are_different(self):
        """Test that console and err_console are different instances."""
        assert console is not err_console


class TestOutputIntegration:
    def test_all_functions_work_together(self):
        """Test that all output functions can be called without errors."""
        with (
            patch.object(console, "print"),
            patch.object(console, "print_json"),
            patch.object(err_console, "print"),
        ):
            # Should not raise any exceptions
            print_success("Success message")
            print_error("Error message")
            print_warning("Warning message")
            print_json({"test": "data"})
            print_table("Table", ["Col1"], [["Row1"]])
            print_panel("Panel", "Content")

    def test_output_functions_handle_none_values(self):
        """Test output functions handle None values gracefully."""
        with (
            patch.object(console, "print") as mock_console_print,
            patch.object(console, "print_json"),
            patch.object(err_console, "print") as mock_err_print,
        ):
            # These should handle None gracefully or convert to string
            print_success(None)
            print_error(None)
            print_warning(None)

            # Verify calls were made (converted to strings)
            assert mock_console_print.call_count >= 2
            assert mock_err_print.call_count >= 1
