"""
Command-line interface for dap-mux.

The ``dap-mux`` command starts the multiplexer, optionally spawning a
debug adapter, and prints the port for editors to connect to.
``dmux`` is a deprecated alias that emits a warning and delegates here.

"""

from __future__ import annotations

import asyncio
import importlib.metadata
import queue
import sys
import threading
from typing import Annotated

import typer
from loguru import logger
from rich.console import Console

from dap_mux.adapter import AdapterProcess, find_free_port
from dap_mux.mux import Multiplexer

_console = Console()

app = typer.Typer(
    name="dap-mux",
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
    headless: Annotated[
        bool,
        typer.Option("--headless", help="Start the multiplexer without the IPython REPL."),
    ] = False,
    no_repl: Annotated[
        bool,
        typer.Option("--no-repl", help="Deprecated: use --headless.", hidden=True),
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

    if no_repl and not headless:
        typer.echo("Warning: --no-repl is deprecated, use --headless instead.", err=True)
        headless = True

    _configure_logging(log_level, log_file)

    try:
        if headless:
            asyncio.run(_run_headless(target, attach, mux_port))
        else:
            _run_with_repl(target, attach, mux_port)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Headless mode (--no-repl)
# ---------------------------------------------------------------------------


async def _run_headless(
    target: str | None,
    attach: str | None,
    mux_port: int,
) -> None:
    """Start adapter (if needed) and mux, then block until cancelled."""
    adapter: AdapterProcess | None = None
    mux = Multiplexer()

    try:
        if attach is not None:
            adapter_host, adapter_port = _parse_attach(attach)
        else:
            assert target is not None
            adapter = AdapterProcess(target, port=find_free_port())
            adapter_port = await adapter.start()
            adapter_host = adapter.host

        await mux.connect_upstream(adapter_host, adapter_port)
        actual_port = await mux.serve("127.0.0.1", mux_port)

        _console.print(f"[bold green]●[/] dap-mux listening on [bold cyan]127.0.0.1:{actual_port}[/] — Ctrl-C to stop")

        await asyncio.Event().wait()

    finally:
        await mux.close()
        if adapter is not None:
            await adapter.stop()


# ---------------------------------------------------------------------------
# REPL mode (default)
# ---------------------------------------------------------------------------


def _run_with_repl(
    target: str | None,
    attach: str | None,
    mux_port: int,
) -> None:
    """Run the mux in a background thread and the IPython REPL in the main thread."""
    port_queue: queue.Queue[int | Exception] = queue.Queue()
    shutdown = threading.Event()

    def _mux_thread() -> None:
        asyncio.run(_run_mux_until(target, attach, mux_port, port_queue, shutdown))

    t = threading.Thread(target=_mux_thread, daemon=True)
    t.start()

    result = port_queue.get(timeout=15.0)
    if isinstance(result, Exception):
        typer.echo(f"Error starting mux: {result}", err=True)
        return

    actual_port = result
    _console.print(f"[bold green]●[/] dap-mux ready — connect your editor to [bold cyan]127.0.0.1:{actual_port}[/]")

    _start_ipython(actual_port)

    shutdown.set()
    t.join(timeout=5.0)


async def _run_mux_until(
    target: str | None,
    attach: str | None,
    mux_port: int,
    port_queue: queue.Queue[int | Exception],
    shutdown: threading.Event,
) -> None:
    """Start adapter (if needed) and mux, signal the port, then wait for shutdown."""
    adapter: AdapterProcess | None = None
    mux = Multiplexer()

    try:
        if attach is not None:
            adapter_host, adapter_port = _parse_attach(attach)
        else:
            assert target is not None
            adapter = AdapterProcess(target, port=find_free_port())
            adapter_port = await adapter.start()
            adapter_host = adapter.host

        await mux.connect_upstream(adapter_host, adapter_port)
        actual_port = await mux.serve("127.0.0.1", mux_port)
        port_queue.put(actual_port)

        while not shutdown.is_set():
            await asyncio.sleep(0.1)

    except Exception as exc:
        port_queue.put(exc)

    finally:
        await mux.close()
        if adapter is not None:
            await adapter.stop()


def _start_ipython(port: int) -> None:
    """Launch an IPython session with dap-mux pre-loaded and connected."""
    from IPython import start_ipython
    from traitlets.config import Config

    c = Config()
    c.InteractiveShellApp.exec_lines = [
        "%load_ext dap_mux.ipython_ext",
        f"%connect 127.0.0.1:{port}",
    ]
    start_ipython(config=c, argv=[])


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


_VALID_LOG_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"})


def _configure_logging(level: str, log_file: str | None) -> None:
    """Set up loguru sinks — this is the only place that configures logging."""
    upper = level.upper()
    if upper not in _VALID_LOG_LEVELS:
        valid = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise typer.BadParameter(f"{level!r} is not a valid log level. Choose from: {valid}")
    logger.remove()
    logger.add(sys.stderr, level=upper)
    if log_file is not None:
        logger.add(log_file, level="DEBUG")


def dmux_deprecated() -> None:
    """Entry point for the deprecated ``dmux`` command."""
    typer.echo(
        "Warning: 'dmux' is deprecated and will be removed in a future release. Use 'dap-mux' instead.",
        err=True,
    )
    app()


__all__ = ("app", "dmux_deprecated")
