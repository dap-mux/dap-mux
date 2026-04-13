# dap-mux

You have your favorite TUI editor (Helix, Neovim, ...). You have a REPL where you explore (IPython, ...). dap-mux connects them — you debug and fully control from within IPython, but see the current line of execution, breakpoints, and stack context in your editor.

This is a uv project, implemented in Python, requiring Python 3.14+.

## Goal

Give terminal-first developers a debugging workflow that combines the exploration power of an IPython REPL with the visual source tracking of their editor — no GUI IDE required.

Today, every debugging tool forces a choice: either you get a REPL with full evaluation power but no source context (ipdb, IPython's `%debug`), or you get an editor with visual breakpoints and stepping but a cramped, limited debug console (VS Code, PyCharm, Neovim's nvim-dap). dap-mux eliminates that choice. Your editor shows where you are. Your REPL is where you work. Both are first-class clients of the same debug session.

**Success looks like:** one command starts everything — the debug adapter, the multiplexer, and the REPL. You set breakpoints in your editor, hit one, and you're sitting at an IPython prompt with full access to the stopped frame. You step from the REPL; the editor's cursor follows. It feels like one tool, not two things wired together.

## Who This Is For

* **Terminal-first developers** using Helix, Neovim, Emacs, or any DAP-capable editor who want IDE-quality debugging without leaving their terminal
* **Data scientists** who live in IPython and want visual source tracking while debugging
* **Remote developers** debugging over SSH where GUI IDEs aren't an option
* **Teams migrating from PyCharm** to terminal workflows who don't want to give up the debugger

## Who This Is Not For

* **Developers happy with VS Code or PyCharm.** If your GUI debugger works, you don't need this.
* **People who want a standalone TUI debugger.** Use [pudb](https://github.com/inducer/pudb) — it's excellent and doesn't need an editor.
* **People looking for a DAP library.** dap-mux is a tool, not a protocol implementation. For typed DAP models, see [dap-python](https://github.com/tomlin7/debug-adapter-client).

## How It Works

dap-mux is a DAP proxy that sits between a debug adapter (like debugpy) and multiple DAP clients. Your editor connects as one client — it shows source, breakpoints, and current position. An IPython REPL connects as another — you step, evaluate expressions, and explore. Both share the same debug session through the multiplexer.

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│    Editor     │◄──TCP──►│              │◄──TCP──►│   debugpy    │
│  (source      │   DAP   │   dap-mux    │   DAP   │  (or any     │
│   display)    │         │              │         │   DA server) │
└──────────────┘         │              │         └──────────────┘
                          │              │
┌──────────────┐         │              │
│  IPython      │◄──TCP──►│              │
│  REPL         │   DAP   │              │
│  (control)    │         └──────────────┘
└──────────────┘
```

The editor is a *display*. The REPL is the *control surface*. Both are first-class DAP clients.

## Status

Early development. Not yet usable.

## Installation

```
pip install dap-mux    # or: uv tool install dap-mux
```

## Usage

```
dmux target.py                # launch mode: starts debugpy for you
dmux --attach 5678            # attach mode: debugpy already running
dmux --attach host:5678       # remote attach
```

Then connect your editor to the multiplexer's port via `:debug-remote` (Helix), `nvim-dap` (Neovim), or any DAP-capable client.

## Compatibility

dap-mux is protocol-agnostic — it speaks DAP, not any specific language or editor. Any editor from the first table can pair with any language from the second through the multiplexer.

### Editors

Any DAP-capable editor works as the display side with zero configuration beyond pointing at the multiplexer's port.

| Editor | DAP integration | Maturity |
|---|---|---|
| **Neovim** | [nvim-dap](https://github.com/mfussenegger/nvim-dap) plugin | Stable |
| **Helix** | Built-in | Experimental |
| **Emacs** | [dap-mode](https://github.com/emacs-lsp/dap-mode) plugin | Stable |
| **Vim** | [Vimspector](https://github.com/puremourning/vimspector) plugin | Stable |
| **Kakoune** | [kak-dap](https://github.com/jdugan6240/kak-dap) plugin | Experimental |

GUI editors (VS Code, Zed, etc.) also work — they speak the same protocol.

### Languages

The REPL+editor workflow requires a language with both a debug adapter and a meaningful interactive REPL. The multiplexer itself works with any DAP adapter regardless of REPL availability.

| Language | Debug adapter | REPL |
|---|---|---|
| **Python** | [debugpy](https://github.com/microsoft/debugpy) (Microsoft) | IPython |
| **Ruby** | [debug](https://github.com/ruby/debug) gem (core team) | IRB, Pry |
| **Julia** | [DebugAdapter.jl](https://github.com/julia-vscode/DebugAdapter.jl) | Julia REPL |
| **Elixir** | [ElixirLS](https://github.com/elixir-lsp/elixir-ls) | IEx |
| **JavaScript/TypeScript** | [js-debug](https://github.com/microsoft/vscode-js-debug) (Microsoft) | Node.js REPL |
| **Clojure** | [cider-nrepl](https://github.com/clojure-emacs/cider-nrepl) | nREPL |
| **R** | [vscDebugger](https://github.com/ManuelHentworking/VSCode-R-Debugger) | radian |
| **Scala** | [scala-debug-adapter](https://github.com/scalacenter/scala-debug-adapter) (Scala Center) | Ammonite |
| **PHP** | [Xdebug](https://xdebug.org/) via [vscode-php-debug](https://github.com/xdebug/vscode-php-debug) | PsySH |
| **Haskell** | [haskell-debug-adapter](https://github.com/phoityne/haskell-debug-adapter) | GHCi |
| **OCaml** | [earlybird](https://github.com/hackwaly/ocamlearlybird) | utop |
| **Common Lisp** | [alive](https://github.com/nobody-famous/alive) | SLIME/SLY |
| **Racket** | [Magic Racket](https://github.com/Eugleo/magic-racket) | Racket REPL |
| **Java** | [java-debug](https://github.com/microsoft/java-debug) (Microsoft) | JShell |
| **C#** | [netcoredbg](https://github.com/Samsung/netcoredbg) (Samsung) | dotnet interactive |

Languages like Go (Delve), Rust (CodeLLDB), C/C++ (lldb-dap), and Swift (lldb-dap) have good DAP support but no meaningful REPL — they still work with the multiplexer for multi-editor scenarios.

dap-mux is currently tested only against debugpy (Python). Other adapters should work but are unvalidated. Reports and patches welcome.

## Limitations

* **Early development.** The core proxy architecture is validated (via spike), but the full tool is not yet built.
* **Tested with debugpy only.** Other debug adapters should work (DAP is a standard protocol) but are not yet validated.
* **Terminal-first by design.** There is no GUI and there won't be one. If you want a graphical debugger, use one — they're good.

## License

[MIT](LICENSE.md)

## Contributing

Not yet accepting contributions — the project is in early development. Watch this space.
