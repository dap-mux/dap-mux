"""Tests for DAP message framing and classification."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from dap_mux.protocol import (
    decode_body,
    decode_header,
    encode_message,
    is_event,
    is_request,
    is_response,
    read_message,
    write_message,
)

# ---------------------------------------------------------------------------
# Message classification
# ---------------------------------------------------------------------------


class TestClassification:
    """Classify messages by their ``type`` field."""

    def test_request(self) -> None:
        msg = {"seq": 1, "type": "request", "command": "initialize"}
        assert is_request(msg)
        assert not is_response(msg)
        assert not is_event(msg)

    def test_response(self) -> None:
        msg = {"seq": 1, "type": "response", "request_seq": 0, "success": True, "command": "initialize"}
        assert is_response(msg)
        assert not is_request(msg)
        assert not is_event(msg)

    def test_event(self) -> None:
        msg = {"seq": 1, "type": "event", "event": "stopped"}
        assert is_event(msg)
        assert not is_request(msg)
        assert not is_response(msg)

    def test_unknown_type(self) -> None:
        msg = {"seq": 1, "type": "bogus"}
        assert not is_request(msg)
        assert not is_response(msg)
        assert not is_event(msg)

    def test_missing_type(self) -> None:
        msg: dict = {"seq": 1}
        assert not is_request(msg)
        assert not is_response(msg)
        assert not is_event(msg)


# ---------------------------------------------------------------------------
# Pure encode / decode
# ---------------------------------------------------------------------------


class TestEncodeDecode:
    """Round-trip through encode_message / decode_header / decode_body."""

    def test_round_trip(self) -> None:
        msg = {"seq": 1, "type": "request", "command": "next"}
        raw = encode_message(msg)
        header, body = raw.split(b"\r\n\r\n", 1)
        header += b"\r\n\r\n"
        length = decode_header(header)
        assert length == len(body)
        assert decode_body(body) == msg

    def test_unicode_body(self) -> None:
        msg = {"seq": 1, "type": "event", "event": "output", "body": {"output": "caf\u00e9\n"}}
        raw = encode_message(msg)
        _header, body = raw.split(b"\r\n\r\n", 1)
        assert decode_body(body) == msg

    def test_decode_header_missing_content_length(self) -> None:
        with pytest.raises(ValueError, match="Missing Content-Length"):
            decode_header(b"X-Custom: foo\r\n\r\n")

    def test_empty_arguments(self) -> None:
        msg = {"seq": 1, "type": "request", "command": "disconnect", "arguments": {}}
        raw = encode_message(msg)
        _header, body = raw.split(b"\r\n\r\n", 1)
        assert decode_body(body) == msg


# ---------------------------------------------------------------------------
# Async framing over streams
# ---------------------------------------------------------------------------


class TestReadMessage:
    """Read DAP messages from an asyncio StreamReader."""

    @pytest.mark.asyncio
    async def test_single_message(self) -> None:
        msg = {"seq": 1, "type": "request", "command": "initialize"}
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message(msg))
        result = await read_message(reader)
        assert result == msg

    @pytest.mark.asyncio
    async def test_two_messages_in_sequence(self) -> None:
        msg_a = {"seq": 1, "type": "request", "command": "initialize"}
        msg_b = {"seq": 2, "type": "request", "command": "configurationDone"}
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message(msg_a) + encode_message(msg_b))
        assert await read_message(reader) == msg_a
        assert await read_message(reader) == msg_b

    @pytest.mark.asyncio
    async def test_connection_closed_during_header(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"Content-Len")
        reader.feed_eof()
        with pytest.raises(ConnectionError, match="header"):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_connection_closed_during_body(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"Content-Length: 100\r\n\r\n{partial")
        reader.feed_eof()
        with pytest.raises((ConnectionError, asyncio.IncompleteReadError)):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_large_message(self) -> None:
        big_value = "x" * 100_000
        msg: dict[str, object] = {"seq": 1, "type": "event", "event": "output", "body": {"output": big_value}}
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message(msg))
        result = await read_message(reader)
        assert cast(dict, result)["body"]["output"] == big_value


class TestWriteMessage:
    """Write DAP messages to an asyncio StreamWriter."""

    @pytest.mark.asyncio
    async def test_write_then_read(self) -> None:
        msg = {"seq": 5, "type": "response", "request_seq": 3, "success": True, "command": "next"}

        # Use a connected socket pair via asyncio streams.
        server_ready = asyncio.Event()
        received: list = []

        async def handle_client(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
            received.append(await read_message(reader))
            server_ready.set()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await write_message(writer, msg)
        writer.close()

        await asyncio.wait_for(server_ready.wait(), timeout=2.0)
        server.close()
        assert received == [msg]
