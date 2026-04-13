"""Tests for the dmux CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from dap_mux.cli import app

runner = CliRunner()


class TestHelp:
    """Basic CLI smoke tests."""

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "DAP multiplexer" in result.output

    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "dap-mux" in result.output


class TestArgValidation:
    """Argument validation without starting anything."""

    def test_no_target_no_attach(self) -> None:
        """Must provide either a target or --attach."""
        result = runner.invoke(app, [])
        assert result.exit_code == 2
        assert "provide a target" in result.output

    def test_both_target_and_attach(self) -> None:
        """Target and --attach are mutually exclusive."""
        result = runner.invoke(app, ["target.py", "--attach", "5678"])
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output


class TestParseAttach:
    """Address parsing for --attach."""

    def test_port_only(self) -> None:
        from dap_mux.cli import _parse_attach

        assert _parse_attach("5678") == ("127.0.0.1", 5678)

    def test_host_and_port(self) -> None:
        from dap_mux.cli import _parse_attach

        assert _parse_attach("192.168.1.1:5678") == ("192.168.1.1", 5678)

    def test_localhost(self) -> None:
        from dap_mux.cli import _parse_attach

        assert _parse_attach("localhost:9999") == ("localhost", 9999)
