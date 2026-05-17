"""
IPython extension for dap-mux.

Provides debug magics that send DAP requests through the multiplexer,
and a background event listener that prints stop notifications above
the IPython prompt.

Load with ``%load_ext dap_mux.ipython_ext`` or automatically via the
CLI.

"""

from __future__ import annotations

import json
import queue
import socket
import threading
from typing import Any

from IPython.core.magic import Magics, line_magic, magics_class
from loguru import logger
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText

from dap_mux.protocol import encode_message

logger = logger.bind(library="dap_mux")

_ENCODING = "utf-8"


class DapConnection:
    """
    Synchronous DAP client connection for use from IPython magics.

    Magics run on the main thread, so this uses blocking sockets
    rather than asyncio. A background thread listens for events.

    """

    def __init__(self) -> None:  # noqa: D107
        self._sock: socket.socket | None = None
        self._seq = 1
        self._send_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._running = False
        self._response_queues: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._queue_lock = threading.Lock()

        # Debug session state.
        self.current_thread_id: int | None = None
        self.current_frame_id: int | None = None
        self.stopped_file: str | None = None
        self.stopped_line: int | None = None

    @property
    def connected(self) -> bool:
        """Whether the connection is open."""
        return self._sock is not None

    def connect(self, host: str, port: int) -> None:
        """Open a TCP connection to the multiplexer and perform DAP handshake."""
        self._sock = socket.create_connection((host, port), timeout=5.0)
        self._sock.settimeout(1.0)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="dap-reader")
        self._reader.start()
        self.send_request(
            "initialize",
            {
                "clientID": "dap-mux-ipython",
                "adapterID": "dap-mux",
                "linesStartAt1": True,
                "columnsStartAt1": True,
                "pathFormat": "path",
            },
        )
        logger.info("Connected to dap-mux at {}:{}", host, port)

    def disconnect(self) -> None:
        """Close the connection."""
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        self.current_thread_id = None
        self.current_frame_id = None
        self.stopped_file = None
        self.stopped_line = None
        logger.info("Disconnected from dap-mux")

    def send_request(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Send a DAP request and wait for the response.

        Returns the response dict, or ``None`` on error.

        """
        if self._sock is None:
            _print_error("Not connected. Use %connect first.")
            return None

        msg: dict[str, Any] = {
            "seq": self._seq,
            "type": "request",
            "command": command,
        }
        if arguments is not None:
            msg["arguments"] = arguments
        self._seq += 1

        # Set up a queue for the response before sending.
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._queue_lock:
            self._response_queues[command] = q

        with self._send_lock:
            try:
                self._sock.sendall(encode_message(msg))
            except OSError as e:
                _print_error(f"Send failed: {e}")
                with self._queue_lock:
                    self._response_queues.pop(command, None)
                return None

        # Wait for the reader thread to deliver the response.
        try:
            return q.get(timeout=10.0)
        except queue.Empty:
            _print_error(f"Timed out waiting for {command} response")
            return None
        finally:
            with self._queue_lock:
                self._response_queues.pop(command, None)

    def _read_loop(self) -> None:
        """Background thread: read all messages, dispatch responses and events."""
        buf = b""
        while self._running and self._sock is not None:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            except TimeoutError:
                continue
            except OSError:
                break

            while b"\r\n\r\n" in buf:
                header_end = buf.index(b"\r\n\r\n") + 4
                header = buf[:header_end].decode("ascii")
                content_length = None
                for line in header.split("\r\n"):
                    if line.startswith("Content-Length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break
                if content_length is None:
                    buf = buf[header_end:]
                    continue

                total_len = header_end + content_length
                if len(buf) < total_len:
                    break

                body = buf[header_end:total_len]
                buf = buf[total_len:]

                try:
                    msg = json.loads(body.decode(_ENCODING))
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "response":
                    self._dispatch_response(msg)
                elif msg.get("type") == "event":
                    self._handle_event(msg)

    def _dispatch_response(self, msg: dict[str, Any]) -> None:
        """Deliver a response to the waiting send_request call."""
        command = msg.get("command", "")
        with self._queue_lock:
            q = self._response_queues.get(command)
        if q is not None:
            q.put(msg)

    def _handle_event(self, msg: dict[str, Any]) -> None:
        """Process a DAP event."""
        event = msg.get("event", "")
        body = msg.get("body", {})

        if event == "stopped":
            self.current_thread_id = body.get("threadId")
            reason = body.get("reason", "unknown")
            _print_notification(f"Stopped ({reason}) on thread {self.current_thread_id}")
            # Auto-fetch stack frame in a separate thread so we don't
            # block the reader thread (which is where _handle_event runs).
            threading.Thread(target=self._auto_fetch_frame, daemon=True).start()

        elif event == "continued":
            self.stopped_file = None
            self.stopped_line = None
            self.current_frame_id = None

        elif event == "terminated":
            _print_notification("Debug session terminated.")
            self.disconnect()

        elif event == "output":
            category = body.get("category", "console")
            output = body.get("output", "")
            if category == "stdout":
                _print_output(output)

    def _auto_fetch_frame(self) -> None:
        """Fetch the top stack frame after a stop to update context."""
        if self.current_thread_id is None:
            return
        resp = self.send_request("stackTrace", {"threadId": self.current_thread_id, "startFrame": 0, "levels": 1})
        if resp and resp.get("success") and resp.get("body"):
            frames = resp["body"].get("stackFrames", [])
            if frames:
                frame = frames[0]
                self.current_frame_id = frame.get("id")
                source = frame.get("source", {})
                self.stopped_file = source.get("path") or source.get("name")
                self.stopped_line = frame.get("line")
                _print_location(self.stopped_file, self.stopped_line, frame.get("name"))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_notification(text: str) -> None:
    """Print a debug notification above the prompt."""
    print_formatted_text(FormattedText([("bold fg:yellow", f"*** {text} ***")]))


def _print_location(file: str | None, line: int | None, func: str | None) -> None:
    """Print the current stop location."""
    parts = []
    if file:
        parts.append(("bold", f"{file}"))
    if line is not None:
        parts.append(("", ":"))
        parts.append(("bold fg:cyan", str(line)))
    if func:
        parts.append(("", " in "))
        parts.append(("italic", func))
    if parts:
        print_formatted_text(FormattedText([("", "  → "), *parts]))


def _print_error(text: str) -> None:
    """Print an error message."""
    print_formatted_text(FormattedText([("bold fg:red", f"Error: {text}")]))


def _print_output(text: str) -> None:
    """Print debuggee stdout output."""
    print_formatted_text(FormattedText([("fg:gray", text.rstrip())]))


# ---------------------------------------------------------------------------
# IPython magics
# ---------------------------------------------------------------------------


@magics_class
class DapMuxMagics(Magics):
    """Debug magics for controlling a DAP session through dap-mux."""

    def __init__(self, shell: Any) -> None:  # noqa: D107
        super().__init__(shell)
        self.conn = DapConnection()

    @line_magic
    def connect(self, line: str) -> None:
        """Connect to the dap-mux multiplexer. Usage: %connect [host:]port."""
        if self.conn.connected:
            _print_error("Already connected. Use %disconnect first.")
            return
        parts = line.strip()
        if not parts:
            _print_error("Usage: %connect [host:]port")
            return
        if ":" in parts:
            host, port_str = parts.rsplit(":", 1)
            host = host or "127.0.0.1"
        else:
            host, port_str = "127.0.0.1", parts
        try:
            port = int(port_str)
        except ValueError:
            _print_error(f"Invalid port: {port_str}")
            return
        self.conn.connect(host, port)
        _print_notification(f"Connected to {host}:{port}")

    @line_magic
    def disconnect(self, line: str) -> None:  # noqa: ARG002
        """Disconnect from the multiplexer. Usage: %disconnect."""
        if not self.conn.connected:
            _print_error("Not connected.")
            return
        self.conn.disconnect()
        _print_notification("Disconnected")

    @line_magic
    def step(self, line: str) -> None:  # noqa: ARG002
        """Step into. Usage: %step."""
        self._stepping_command("stepIn")

    @line_magic
    def s(self, line: str) -> None:  # noqa: ARG002
        """Step into (alias for %step). Usage: %s."""
        self._stepping_command("stepIn")

    @line_magic
    def next(self, line: str) -> None:  # noqa: ARG002
        """Step over. Usage: %next."""
        self._stepping_command("next")

    @line_magic
    def n(self, line: str) -> None:  # noqa: ARG002
        """Step over (alias for %next). Usage: %n."""
        self._stepping_command("next")

    @line_magic
    def continue_(self, line: str) -> None:  # noqa: ARG002
        """Continue execution. Usage: %continue_."""
        self._stepping_command("continue")

    @line_magic
    def c(self, line: str) -> None:  # noqa: ARG002
        """Continue execution (alias). Usage: %c."""
        self._stepping_command("continue")

    @line_magic
    def finish(self, line: str) -> None:  # noqa: ARG002
        """Step out of the current function. Usage: %finish."""
        self._stepping_command("stepOut")

    def _stepping_command(self, command: str) -> None:
        """Send a stepping request for the current thread."""
        if self.conn.current_thread_id is None:
            _print_error("Not stopped on any thread.")
            return
        self.conn.send_request(command, {"threadId": self.conn.current_thread_id})

    @line_magic
    def bt(self, line: str) -> None:  # noqa: ARG002
        """Show backtrace. Usage: %bt."""
        if self.conn.current_thread_id is None:
            _print_error("Not stopped on any thread.")
            return
        resp = self.conn.send_request("stackTrace", {"threadId": self.conn.current_thread_id})
        if not resp or not resp.get("success"):
            _print_error("Failed to get stack trace.")
            return
        frames = resp.get("body", {}).get("stackFrames", [])
        for i, frame in enumerate(frames):
            source = frame.get("source", {})
            path = source.get("path") or source.get("name") or "?"
            line_num = frame.get("line", "?")
            name = frame.get("name", "?")
            marker = "→ " if frame.get("id") == self.conn.current_frame_id else "  "
            print_formatted_text(
                FormattedText(
                    [
                        ("bold" if i == 0 else "", f"{marker}#{i} {name} at {path}:{line_num}"),
                    ]
                )
            )

    @line_magic
    def frame(self, line: str) -> None:
        """Select a stack frame by index. Usage: %frame N."""
        if self.conn.current_thread_id is None:
            _print_error("Not stopped on any thread.")
            return
        try:
            idx = int(line.strip())
        except ValueError:
            _print_error("Usage: %frame N")
            return
        resp = self.conn.send_request("stackTrace", {"threadId": self.conn.current_thread_id})
        if not resp or not resp.get("success"):
            _print_error("Failed to get stack trace.")
            return
        frames = resp.get("body", {}).get("stackFrames", [])
        if idx < 0 or idx >= len(frames):
            _print_error(f"Frame index {idx} out of range (0-{len(frames) - 1}).")
            return
        frame = frames[idx]
        self.conn.current_frame_id = frame.get("id")
        source = frame.get("source", {})
        self.conn.stopped_file = source.get("path") or source.get("name")
        self.conn.stopped_line = frame.get("line")
        _print_location(self.conn.stopped_file, self.conn.stopped_line, frame.get("name"))

    @line_magic("eval")
    def eval_(self, line: str) -> None:
        """Evaluate an expression in the debuggee's frame. Usage: %eval expr."""
        if not line.strip():
            _print_error("Usage: %eval expression")
            return
        if self.conn.current_frame_id is None:
            _print_error("No active frame. Are you stopped at a breakpoint?")
            return
        resp = self.conn.send_request(
            "evaluate",
            {
                "expression": line.strip(),
                "frameId": self.conn.current_frame_id,
                "context": "repl",
            },
        )
        if not resp:
            return
        if resp.get("success"):
            result = resp.get("body", {}).get("result", "")
            print_formatted_text(FormattedText([("fg:green", result)]))
        else:
            error_msg = resp.get("message", "Evaluation failed")
            _print_error(error_msg)

    @line_magic("break")
    def break_(self, line: str) -> None:
        """Set a breakpoint. Usage: %break file:line [condition]."""
        parts = line.strip().split(None, 1)
        if not parts:
            _print_error("Usage: %break file:line [condition]")
            return
        location = parts[0]
        condition = parts[1] if len(parts) > 1 else None

        if ":" not in location:
            _print_error("Usage: %break file:line [condition]")
            return
        file_path, line_str = location.rsplit(":", 1)
        try:
            line_num = int(line_str)
        except ValueError:
            _print_error(f"Invalid line number: {line_str}")
            return

        bp: dict[str, Any] = {"line": line_num}
        if condition:
            bp["condition"] = condition

        resp = self.conn.send_request(
            "setBreakpoints",
            {
                "source": {"path": file_path},
                "breakpoints": [bp],
            },
        )
        if resp and resp.get("success"):
            bps = resp.get("body", {}).get("breakpoints", [])
            for b in bps:
                if b.get("verified"):
                    _print_notification(f"Breakpoint set at {file_path}:{b.get('line', line_num)}")
                else:
                    _print_error(f"Breakpoint at {file_path}:{line_num} not verified")
        else:
            _print_error("Failed to set breakpoint")

    @line_magic
    def sync(self, line: str) -> None:  # noqa: ARG002
        """Sync stopped state from the session. Usage: %sync."""
        if not self.conn.connected:
            _print_error("Not connected.")
            return
        resp = self.conn.send_request("threads")
        if not resp or not resp.get("success"):
            _print_error("Failed to get thread list.")
            return
        for thread in resp.get("body", {}).get("threads", []):
            tid = thread.get("id")
            if tid is None:
                continue
            st = self.conn.send_request("stackTrace", {"threadId": tid, "startFrame": 0, "levels": 1})
            if st and st.get("success") and st.get("body", {}).get("stackFrames"):
                frame = st["body"]["stackFrames"][0]
                self.conn.current_thread_id = tid
                self.conn.current_frame_id = frame.get("id")
                source = frame.get("source", {})
                self.conn.stopped_file = source.get("path") or source.get("name")
                self.conn.stopped_line = frame.get("line")
                _print_notification(f"Synced: stopped on thread {tid}")
                _print_location(self.conn.stopped_file, self.conn.stopped_line, frame.get("name"))
                return
        _print_notification("No stopped threads found.")

    @line_magic
    def clear(self, line: str) -> None:
        """Remove breakpoints from a file. Usage: %clear file:line."""
        parts = line.strip()
        if not parts or ":" not in parts:
            _print_error("Usage: %clear file:line")
            return
        file_path, _line_str = parts.rsplit(":", 1)
        # Clear all breakpoints in the file by sending an empty list.
        resp = self.conn.send_request(
            "setBreakpoints",
            {
                "source": {"path": file_path},
                "breakpoints": [],
            },
        )
        if resp and resp.get("success"):
            _print_notification(f"Breakpoints cleared in {file_path}")
        else:
            _print_error("Failed to clear breakpoints")


# ---------------------------------------------------------------------------
# Extension entry point
# ---------------------------------------------------------------------------


def load_ipython_extension(ipython: Any) -> None:
    """Register dap-mux magics with IPython."""
    ipython.register_magics(DapMuxMagics)


__all__ = (
    "DapConnection",
    "DapMuxMagics",
    "load_ipython_extension",
)
