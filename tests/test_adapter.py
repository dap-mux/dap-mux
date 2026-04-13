"""Tests for debug adapter lifecycle management."""

from __future__ import annotations

import asyncio

import pytest

from dap_mux.adapter import AdapterProcess, find_free_port, wait_for_port


class TestFindFreePort:
    """Port allocation utility."""

    def test_returns_valid_port(self) -> None:
        port = find_free_port()
        assert 1024 <= port <= 65535

    def test_returns_different_ports(self) -> None:
        ports = {find_free_port() for _ in range(10)}
        # Not guaranteed to be all unique, but very likely.
        assert len(ports) > 1


class TestWaitForPort:
    """Polling until a port accepts connections."""

    @pytest.mark.asyncio
    async def test_connects_to_listening_port(self) -> None:
        """Returns immediately when the port is already listening."""
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        await wait_for_port("127.0.0.1", port, timeout=2.0)
        server.close()
        await server.wait_closed()

    @pytest.mark.asyncio
    async def test_times_out_on_closed_port(self) -> None:
        """Raises TimeoutError when nothing is listening."""
        port = find_free_port()
        with pytest.raises(TimeoutError, match="Timed out"):
            await wait_for_port("127.0.0.1", port, timeout=0.3)

    @pytest.mark.asyncio
    async def test_waits_for_delayed_listener(self) -> None:
        """Succeeds when the listener starts after a short delay."""
        port = find_free_port()

        async def delayed_listen() -> asyncio.Server:
            await asyncio.sleep(0.3)
            return await asyncio.start_server(lambda r, w: None, "127.0.0.1", port)

        server_task = asyncio.create_task(delayed_listen())
        await wait_for_port("127.0.0.1", port, timeout=2.0)

        server = await server_task
        server.close()
        await server.wait_closed()


class TestAdapterProcess:
    """Spawning and managing a debugpy subprocess."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        """Start a simple Python script as a 'fake' adapter and stop it."""
        # We use a tiny Python script that just listens on a port,
        # rather than actual debugpy, to keep tests fast and dependency-free.
        port = find_free_port()
        adapter = AdapterProcess.__new__(AdapterProcess)
        adapter._target = "-"
        adapter._host = "127.0.0.1"
        adapter._port = port
        adapter._python = "python3"
        adapter._adapter_args = []
        adapter._process = None
        adapter._output_task = None

        # Spawn a simple TCP listener as the "adapter".
        script = f"import socket, time; s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(1); time.sleep(30)"
        adapter._process = await asyncio.create_subprocess_exec(
            "python3",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        adapter._output_task = asyncio.create_task(adapter._capture_output())

        await wait_for_port("127.0.0.1", port, timeout=3.0)
        assert adapter.is_running

        rc = await adapter.stop()
        assert not adapter.is_running
        assert rc is not None

    @pytest.mark.asyncio
    async def test_properties(self) -> None:
        """Host and port properties are set correctly."""
        adapter = AdapterProcess("target.py", host="127.0.0.1", port=12345)
        assert adapter.host == "127.0.0.1"
        assert adapter.port == 12345
        assert not adapter.is_running

    @pytest.mark.asyncio
    async def test_auto_port(self) -> None:
        """Port 0 causes a free port to be selected."""
        adapter = AdapterProcess("target.py", port=0)
        assert 1024 <= adapter.port <= 65535

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self) -> None:
        """Stopping before starting returns None."""
        adapter = AdapterProcess("target.py")
        result = await adapter.stop()
        assert result is None
