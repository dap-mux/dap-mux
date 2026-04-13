"""
Command-line interface for dap-mux.

The ``dmux`` command starts the multiplexer, optionally spawning a
debug adapter, and prints the port for editors to connect to.

"""

from __future__ import annotations

import asyncio
import importlib.metadata
import sys
from typing import Annotated

import typer
from loguru import logger

from dap_mux.adapter import AdapterProcess, find_free_port
from dap_mux.mux import Multiplexer

app = typer.Typer(
    name="dmux",
    help="DAP multiplexer — debug from a REPL while your editor shows where you are.",
    add_completion=False,
)


def _version_callback(value: bool) -> None:  # noqa: FBT001
    """Print the version and exit."""
    if value:
        version = importlib.metadata.version("dap-mux")
        typer.echo(f"dap-mux {version}")
        raise typer.Exit


def _parse_attach(value: str) -> tuple[str, int]:
    """
    Parse an attach address like ``5678`` or ``host:5678``.

    Returns ``(host, port)``.

    """
    if ":" in value:
        host, port_str = value.rsplit(":", 1)
        return host, int(port_str)
    return "127.0.0.1", int(value)


@app.command()
def main(
    target: Annotated[
        str | None,
        typer.Argument(help="Python script to debug (launch mode)."),
    ] = None,
    attach: Annotated[
        str | None,
        typer.Option("--attach", "-a", help="Attach to an already-running debug adapter ([host:]port)."),
    ] = None,
    mux_port: Annotated[
        int,
        typer.Option("--mux-port", "-p", help="Port for DAP clients to connect to (0 = auto)."),
    ] = 0,
    log_level: Annotated[
        str,
        typer.Option("--log-level", "-l", help="Log level (DEBUG, INFO, WARNING, ERROR)."),
    ] = "WARNING",
    log_file: Annotated[
        str | None,
        typer.Option("--log-file", help="Also write logs to this file."),
    ] = None,
    no_repl: Annotated[
        bool,
        typer.Option("--no-repl", help="Start the multiplexer without the IPython REPL."),
    ] = False,
    version: Annotated[  # noqa: ARG001
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Start the DAP multiplexer."""
    if target is None and attach is None:
        typer.echo("Error: provide a target script or --attach. See --help.", err=True)
        raise typer.Exit(code=2)
    if target is not None and attach is not None:
        typer.echo("Error: --attach and a target script are mutually exclusive.", err=True)
        raise typer.Exit(code=2)

    _configure_logging(log_level, log_file)

    try:
        asyncio.run(_run(target, attach, mux_port, no_repl))
    except KeyboardInterrupt:
        pass


async def _run(
    target: str | None,
    attach: str | None,
    mux_port: int,
    no_repl: bool,
) -> None:
    """Async entry point: start adapter (if needed), mux, and wait."""
    adapter: AdapterProcess | None = None
    mux = Multiplexer()

    try:
        if attach is not None:
            adapter_host, adapter_port = _parse_attach(attach)
        else:
            assert target is not None
            adapter_port_num = find_free_port()
            adapter = AdapterProcess(target, port=adapter_port_num)
            adapter_port = await adapter.start()
            adapter_host = adapter.host

        await mux.connect_upstream(adapter_host, adapter_port)
        actual_port = await mux.serve("127.0.0.1", mux_port)

        typer.echo(f"dap-mux listening on 127.0.0.1:{actual_port}")
        typer.echo(f"Connect your editor to 127.0.0.1:{actual_port}")

        if no_repl:
            # Block until cancelled.
            await asyncio.Event().wait()
        else:
            # TODO: start IPython REPL (M6)
            typer.echo("REPL not yet implemented — running in headless mode.")
            typer.echo("Press Ctrl-C to stop.")
            await asyncio.Event().wait()

    finally:
        await mux.close()
        if adapter is not None:
            await adapter.stop()


def _configure_logging(level: str, log_file: str | None) -> None:
    """Set up loguru sinks — this is the only place that configures logging."""
    logger.remove()
    logger.add(sys.stderr, level=level.upper())
    if log_file is not None:
        logger.add(log_file, level="DEBUG")


__all__ = ("app",)
