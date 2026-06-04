# dap-mux

Every terminal debugger forces a choice: a REPL with full evaluation power but no source context, or an editor with visual breakpoints but a crippled debug console. dap-mux removes the need to choose.

Connect your editor and your REPL to the same debug session simultaneously. Step from your REPL while your editor tracks the current line. Evaluate arbitrary expressions in the stopped frame. Set breakpoints from either side.

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│    Helix      │◄──DAP──►│              │◄──DAP──►│   debugpy    │
│  source view  │         │   dap-mux    │         │  (or any     │
│  breakpoints  │         │              │         │   DA server) │
└──────────────┘         │              │         └──────────────┘
                          │              │
┌──────────────┐         │              │
│  your REPL    │◄──DAP──►│              │
│  evaluation   │         └──────────────┘
│  stepping     │
└──────────────┘
```

dap-mux is a DAP proxy. It sits between a debug adapter and multiple clients, routing requests, broadcasting events, and replaying session state to clients that join late. Your editor and your REPL are both first-class DAP clients sharing one session through the multiplexer.

The bundled REPL frontend is an IPython extension — a debug control surface that gives IPython's `%magic` interface DAP connectivity. It's the REPL the author uses. Other REPLs can connect to the multiplexer too; they just don't have a built-in frontend yet.

## Goals

**Your** editor + **your** language + **your** debugger + **your** REPL — and anything else you want to connect. Your tool choices should compose freely. dap-mux is the connector; the tools are yours.

The commitments that follow from this:

**Standard DAP at every boundary.** Any DAP-capable editor, REPL, or tool connects to the client-facing interface without special plugins or configuration. Any standard DAP adapter works upstream. Every connection point speaks the standard.

**Every connected client is first-class.** All clients can perform any standard DAP operation: set breakpoints, step, evaluate expressions, inspect the call stack, select frames. No client is read-only.

**Sessions survive client changes.** Connecting or disconnecting a client never interrupts the session or restarts the adapter. Connect a second editor mid-session. Disconnect the REPL and reconnect. The session continues.

**Late joiners see current state.** A client connecting after initialization receives the initialized handshake and, if stopped, the current stop position. An editor joined mid-session immediately shows the correct line.

## Status

v0.9.0 is the first public release — the first time it has been possible for anyone other than the author to run this tool. Until now it has been developed and tested privately.

The core mechanics — protocol framing, sequence rewriting, multi-client routing, event broadcasting, late-join state replay — have been tested live and are covered by a test suite. The workflow it enables is real: connect Helix or VS Code and an IPython REPL to the same debugpy session and debug from both simultaneously.

That's two editors, one debug adapter, one REPL, on two platforms. The goals call for any editor, any language, any adapter — and most of that territory has never been touched by anyone. There is much to find and fix. Bug reports, notes from people testing other combinations, and contributions that expand the proven ground are exactly what this project needs right now.

## Requirements

[uv](https://docs.astral.sh/uv/) — it manages the Python runtime automatically.

debugpy must be available in the *target* environment. dap-mux connects to it over TCP and never imports it directly:

```
pip install debugpy    # in your project's virtualenv
```

## Installation

```
uv tool install dap-mux
```

For development:

```
git clone https://github.com/dap-mux/dap-mux
cd dap-mux
uv sync --group dev
```

## Quick Start

This example uses Helix and the built-in IPython frontend. Any DAP-capable editor works — see [Editor Setup](#editor-setup).

**1. Start the session**

```
dap-mux script.py
```

dap-mux spawns debugpy, connects the multiplexer, and opens an IPython REPL:

```
dap-mux listening on 127.0.0.1:5679
Connect your editor to 127.0.0.1:5679
```

The IPython prompt appears. The script is paused — it won't start running until an editor client sends `configurationDone`.

**2. Set breakpoints in Helix, then connect**

Open the script in Helix and set a breakpoint on the line you want to pause on (`<space>b` or your configured key). Then connect:

```
:debug-remote 127.0.0.1:5679 attach
```

> **Set breakpoints before connecting.** When Helix connects it sends `configurationDone`, which starts the script. With no breakpoints, the script runs to completion before you can do anything.

Execution starts and pauses at your breakpoint. Helix highlights the current line. IPython prints the stop location.

**3. Debug from IPython**

```python
%bt              # call stack
%eval results    # evaluate expression in the stopped frame
%frame 2         # switch to a different stack frame (%eval follows)
%n               # step over
%s               # step into
%c               # continue
%finish          # step out
%break script.py:42   # set a breakpoint
```

Bare Python at the IPython prompt runs locally. `%eval` evaluates in the debuggee's frame.

---

## Usage

### Launch mode

```
dap-mux script.py
```

Spawns debugpy attached to `script.py`, starts the multiplexer, opens the IPython REPL. Everything in one command.

### Attach mode

When debugpy is already running:

```
dap-mux --attach 5678
dap-mux --attach 192.168.1.10:5678
```

The IPython REPL connects to the existing session. Use `%sync` to discover the current stopped state if the session was already paused when you joined.

### Headless mode

Use `--headless` to start the multiplexer without the IPython REPL. Connect your own tools — any editor, any REPL frontend that speaks DAP.

```
dap-mux script.py --headless
dap-mux --attach 5678 --headless
```

**What launches what:**

In launch mode (`dap-mux script.py --headless`), dap-mux spawns debugpy attached to the Python script, starts the multiplexer, and waits. You connect your own clients.

In attach mode (`dap-mux --attach host:port --headless`), dap-mux connects to an already-running debug adapter — any language, any adapter. *You* are responsible for starting the adapter first.

**Using dap-mux with another language**

The multiplexer speaks standard DAP and works with any debug adapter. Here is a Ruby example using [rdbg](https://github.com/ruby/debug):

```
# Terminal 1 — start the Ruby debug adapter
rdbg --open --port 5678 script.rb

# Terminal 2 — start the multiplexer
dap-mux --attach 5678 --headless
# dap-mux listening on 127.0.0.1:5679

# Now connect your editor to 127.0.0.1:5679 as a DAP server
```

Any DAP-capable editor connects immediately. A REPL frontend — the equivalent of the IPython extension for Ruby, Julia, or another language — does not exist yet and needs to be built. The multiplexer is ready; the frontend is the contribution.

### CLI reference

```
dap-mux [TARGET] [OPTIONS]

Arguments:
  TARGET                   Python script to debug (launch mode)

Options:
  --attach, -a  TEXT       Attach to a running debug adapter ([host:]port)
  --mux-port, -p  INT      Port for clients to connect to (0 = auto)  [default: 0]
  --log-level, -l  TEXT    Log level: DEBUG, INFO, WARNING, ERROR  [default: WARNING]
  --log-file  TEXT         Also write logs to this file
  --headless               Start without the IPython REPL
  --version, -V            Show version and exit
```

---

## Editor Setup

### Helix

Add to `~/.config/helix/languages.toml`:

```toml
[[language]]
name = "python"

[language.debugger]
name = "debugpy"
transport = "tcp"
command = "python3"
args = ["-m", "debugpy"]
port-arg = "--listen=127.0.0.1:{}"

[[language.debugger.templates]]
name = "launch"
request = "launch"
completion = [{ name = "script", completion = "filename" }]
args = { mode = "debug", program = "{0}" }

[[language.debugger.templates]]
name = "attach"
request = "attach"
completion = []
args = {}
```

Connect to a running dap-mux with `:debug-remote host:port attach`.

A working copy of this configuration is in [`demos/helix/`](demos/helix/).

### VS Code

Install the [Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy) extension (`ms-python.debugpy`), then add to `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Connect to dap-mux",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "127.0.0.1",
                "port": 5679
            }
        }
    ]
}
```

Start dap-mux with a pinned port (`dap-mux script.py -p 5679`) so the launch config can hardcode it. Set breakpoints in VS Code before running the configuration — launching it sends `configurationDone` and starts execution.

A working copy of this configuration is in [`demos/vscode/`](demos/vscode/).

### Neovim

Configure nvim-dap to connect to the mux port as a DAP server. Point `dap.adapters` at `127.0.0.1:<mux-port>` with `type = "server"`.

### Other editors

Any editor with a DAP client works. Configure it to connect to `127.0.0.1:<mux-port>` as an existing DAP server — dap-mux speaks standard DAP, no special configuration needed.

---

## IPython Extension

dap-mux ships with an IPython extension that turns IPython into a debug control surface. Load it with `%load_ext dap_mux`, or use `dap-mux` which loads it automatically.

| Magic | Alias | Description |
|---|---|---|
| `%connect [host:]port` | | Connect to the multiplexer |
| `%disconnect` | | Disconnect |
| `%sync` | | Discover current stopped state (useful after late-joining a paused session) |
| `%bt` | | Call stack |
| `%frame N` | | Select stack frame; subsequent `%eval` evaluates in that frame's scope |
| `%eval expr` | | Evaluate expression in the current frame |
| `%step` | `%s` | Step into |
| `%next` | `%n` | Step over |
| `%continue_` | `%c` | Continue execution |
| `%finish` | | Step out of current function |
| `%break file:line [cond]` | | Set breakpoint (optional condition) |
| `%clear file:line` | | Remove all breakpoints in file |

`%eval` evaluates in the debuggee's frame — it has access to the local and global variables at the current stop point. Regular IPython expressions evaluate locally.

---

## How It Works

Each DAP client (editor, REPL) connects to dap-mux over TCP. The multiplexer rewrites sequence numbers so all clients share a single upstream connection to the debug adapter. Responses are routed back to the client that made the request. Events are broadcast to all connected clients.

When a client joins after the session is already initialized, dap-mux replays the cached `initialized` event and, if the session is currently stopped, the last `stopped` event — so the late joiner sees current state immediately without requiring an adapter restart.

dap-mux is written in Python. The tool is a network I/O router — it reads JSON from one TCP connection and writes it to others — and Python's `asyncio` is purpose-built for exactly this. The actual performance ceiling is human keystroke speed; the multiplexer will never be CPU-bound. The IPython integration is the other reason: it runs in the same process, with direct access to IPython's internals. A Go or Rust implementation would have to shell out to Python and do IPC to achieve the same result, trading a clean in-process design for a messy out-of-process one.

---

## Who This Is For

* **Terminal-first developers** using Helix, Neovim, Emacs, or any DAP-capable editor who want IDE-quality debugging without leaving the terminal
* **Data scientists** who live in IPython and want visual source tracking while debugging
* **Remote developers** debugging over SSH where GUI IDEs are impractical
* **Anyone** who has wished their debug REPL had tab completion, history, and the ability to `import` things

---

## Compatibility

### Editors

Any DAP-capable editor works as a display client — connect it to the mux port like any other DAP server.

| Editor | DAP integration | Status |
|---|---|---|
| **Helix** | Built-in | Tested |
| **VS Code** | Built-in | Tested |
| **Neovim** | [nvim-dap](https://github.com/mfussenegger/nvim-dap) | Untested |
| **Emacs** | [dap-mode](https://github.com/emacs-lsp/dap-mode) | Untested |
| **Vim** | [Vimspector](https://github.com/puremourning/vimspector) | Untested |

### Languages

The REPL + editor workflow is richest for languages with a capable interactive REPL. The multiplexer itself works with any DAP adapter.

| Language | Debug adapter | REPL |
|---|---|---|
| **Python** | [debugpy](https://github.com/microsoft/debugpy) | IPython ← tested |
| **Ruby** | [debug](https://github.com/ruby/debug) gem | IRB, Pry |
| **Julia** | [DebugAdapter.jl](https://github.com/julia-vscode/DebugAdapter.jl) | Julia REPL |
| **Elixir** | [ElixirLS](https://github.com/elixir-lsp/elixir-ls) | IEx |
| **JavaScript** | [js-debug](https://github.com/microsoft/vscode-js-debug) | Node.js REPL |

Languages with strong DAP support but no meaningful REPL — Go (Delve), Rust (codelldb), C/C++ (lldb-dap) — still benefit from dap-mux for multi-editor sessions and reconnection without restarting.

dap-mux is tested against debugpy. Other adapters should work (DAP is a standard protocol) but are unvalidated.

### Platforms

| Platform | Status |
|---|---|
| **Linux** | Tested |
| **macOS** | Tested |
| **Windows** | Intended; not yet validated |

---

## What this is not

**dap-mux is a router, not a debugger.** It forwards DAP messages between your tools and your debug adapter. It does not execute code, inspect memory, or understand the state of your program. Everything it connects already does those things — dap-mux provides the connectivity, not the capability.

**It does not add debugging features your adapter doesn't already have.** If your debug adapter doesn't support something, dap-mux won't supply it. The power comes from the tools you bring. dap-mux connects them.

**Terminal-first by design.** There is no GUI and there won't be — and on the command line, the only real interaction is starting it. After that, you're working in your editor and your REPL, not in dap-mux.

**The IPython extension is Python-specific.** The multiplexer works with any language that has a DAP adapter. The bundled REPL integration is built on IPython and is Python-only. Other language REPLs are possible frontends, but they aren't built in.

**dap-mux is one component in a pipeline, not an all-in-one tool.** If you want a self-contained TUI debugger with its own UI, [pudb](https://github.com/inducer/pudb) is excellent and actively maintained. dap-mux is for a different way of working: your editor does one thing well, your REPL does one thing well, your debug adapter does one thing well — dap-mux connects them. Unix has always worked this way.

## Limitations

* **Tested with debugpy only.** Other debug adapters should work but haven't been validated.
* **Windows support is untested.** The code has no known platform-specific dependencies, but it hasn't been validated on Windows yet.

---

## License

[MIT](LICENSE.md)

## Contributing

Issues and feedback welcome. The project is young — bug reports and notes on adapters or editors you've tested are especially useful.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set up a development environment, what makes a good PR, and what the project will and won't accept. See [CHANGELOG.md](CHANGELOG.md) for what has changed.
