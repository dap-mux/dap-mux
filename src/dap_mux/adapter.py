"""
Debug adapter lifecycle management.

An ``AdapterProcess`` spawns a debug adapter (typically debugpy) as a
subprocess, waits for it to start listening, and provides graceful
shutdown. The multiplexer uses this in launch mode; in attach mode
the adapter is already running externally.

"""

from __future__ import annotations

import asyncio
import socket
import sys
from typing import Any

from loguru import logger

logger = logger.bind(library="dap_mux")

_CONNECT_POLL_INTERVAL = 0.1
_CONNECT_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 5.0


def find_free_port() -> int:
    """
    Find a free TCP port on localhost.

    >>> port = find_free_port()
    >>> 1024 <= port <= 65535
    True

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_for_port(host: str, port: int, timeout: float = _CONNECT_TIMEOUT) -> None:
    """
    Poll until *host*:*port* accepts a TCP connection.

    Raises ``TimeoutError`` if the port isn't reachable within *timeout*
    seconds.

    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            _reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return
        except ConnectionRefusedError, OSError:
            await asyncio.sleep(_CONNECT_POLL_INTERVAL)
    msg = f"Timed out waiting for {host}:{port} after {timeout}s"
    raise TimeoutError(msg)


class AdapterProcess:
    """
    Manage a debug adapter subprocess.

    Typical usage::

        adapter = AdapterProcess("target.py")
        port = await adapter.start()
        # ... connect the multiplexer to localhost:port ...
        await adapter.stop()

    """

    def __init__(  # noqa: D107
        self,
        target: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        python: str | None = None,
        adapter_args: list[str] | None = None,
    ) -> None:
        self._target = target
        self._host = host
        self._port = port or find_free_port()
        self._python = python or sys.executable
        self._adapter_args = adapter_args or []
        self._process: asyncio.subprocess.Process | None = None
        self._output_task: asyncio.Task[None] | None = None

    @property
    def port(self) -> int:
        """The port the adapter is listening on."""
        return self._port

    @property
    def host(self) -> str:
        """The host the adapter is listening on."""
        return self._host

    @property
    def is_running(self) -> bool:
        """Whether the adapter subprocess is still alive."""
        return self._process is not None and self._process.returncode is None

    async def start(self) -> int:
        """
        Spawn debugpy and wait for it to start listening.

        Returns the port the adapter is listening on.

        """
        cmd = [
            self._python,
            "-m",
            "debugpy",
            "--listen",
            f"{self._host}:{self._port}",
            "--wait-for-client",
            *self._adapter_args,
            self._target,
        ]
        logger.info("Starting debug adapter: {}", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._output_task = asyncio.create_task(
            self._capture_output(),
            name="adapter-output",
        )

        await wait_for_port(self._host, self._port)
        logger.info("Debug adapter listening on {}:{}", self._host, self._port)
        return self._port

    async def stop(self) -> int | None:
        """
        Shut down the adapter subprocess gracefully.

        Sends SIGTERM first, then SIGKILL after a timeout. Returns the
        exit code, or ``None`` if the process was not running.

        """
        if self._process is None:
            return None

        if self._process.returncode is not None:
            return self._await_cleanup()

        logger.info("Stopping debug adapter (pid={})", self._process.pid)
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=_SHUTDOWN_TIMEOUT)
        except TimeoutError:
            logger.warning("Debug adapter did not exit after {}s, killing", _SHUTDOWN_TIMEOUT)
            self._process.kill()
            await self._process.wait()

        return self._await_cleanup()

    def _await_cleanup(self) -> int | None:
        """Cancel the output capture task and return the exit code."""
        if self._output_task is not None:
            self._output_task.cancel()
            self._output_task = None
        rc = self._process.returncode if self._process else None
        logger.info("Debug adapter exited with code {}", rc)
        self._process = None
        return rc

    async def _capture_output(self) -> None:
        """Log adapter stdout/stderr via loguru."""
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None

        async def _stream(
            stream: asyncio.StreamReader,
            log_fn: Any,
            label: str,
        ) -> None:
            try:
                async for line in stream:
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        log_fn("debugpy {}: {}", label, text)
            except asyncio.CancelledError:
                pass

        await asyncio.gather(
            _stream(self._process.stdout, logger.debug, "stdout"),
            _stream(self._process.stderr, logger.debug, "stderr"),
        )


__all__ = (
    "AdapterProcess",
    "find_free_port",
    "wait_for_port",
)
