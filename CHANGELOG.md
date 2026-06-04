# Changelog

## v0.10.0 (2026-06-04)

IPython is now an optional extra, not a required dependency.

**Breaking changes:**
* `uv tool install dap-mux` no longer includes IPython. Install `dap-mux[ipython]` for the Python + IPython workflow. Headless mode and all non-Python workflows are unaffected.

**Fixes:**
* Eliminated the spurious "Timed out waiting for attach response" error on startup in launch mode.

**Documentation:**
* `uv tool install` is now the recommended and primary installation method.
* New Ecosystem section — [dap-observer](https://github.com/shaleh/dap-observer) by Sean Perry is the first third-party tool built for this ecosystem.
* Rust (codelldb) and VS Code added to the tested combinations.

## v0.9.5 (2026-06-04)

Rename CLI entry point and add Rust demo.

**Changes:**
* `dap-mux` is now the canonical command name. `dmux` still works but prints a deprecation warning and will be removed in a future release.

**Demos:**
* Rust demo: Dijkstra's shortest path debugged with codelldb, dap-observer, and Helix — the first non-Python demo showing dap-mux with an external debug adapter

## v0.9.3 (2026-05-31)

Add `--headless` flag and document non-Python workflows.

**Features:**
* `--headless` replaces `--no-repl` as the preferred flag for starting without the IPython REPL
* `--no-repl` still works but prints a deprecation warning

**Documentation:**
* Headless mode section rewritten to explain what gets launched where and how to use dap-mux with other languages
* Ruby/rdbg example showing the attach + headless workflow
* Notes that REPL frontends for other languages are the next contribution opportunity

## v0.9.2 (2026-05-30)

Fix publish workflow permissions so the build job can check out the repository.

**Internal:**
* Add `contents: read` permission to the build job in `publish.yml` — required when the top-level workflow sets `permissions: {}`

## v0.9.1 (2026-05-30)

Update installation instructions now that dap-mux is on PyPI.

**Documentation:**
* Installation command is now `uv tool install dap-mux`
* Remove "not yet on PyPI" from Limitations

## v0.9.0 (2026-05-30)

First release. The core multiplexer is complete and live-tested: connect Helix or VS Code and an IPython REPL to the same debugpy session and debug from both simultaneously.

**Features:**
* DAP multiplexer with full protocol support — framing, sequence rewriting, multi-client routing, event broadcasting
* Late-join state replay — a client connecting to an already-running session receives the initialized handshake and current stop position immediately
* Launch mode (`dap-mux script.py`) spawns debugpy and opens the IPython REPL in one command
* Attach mode (`dap-mux --attach host:port`) connects to an already-running debug adapter
* IPython extension with debug magics: `%step`, `%next`, `%continue_`, `%finish`, `%bt`, `%frame`, `%eval`, `%break`, `%clear`, `%sync`, `%connect`, `%disconnect`
* Headless mode (`--no-repl`) for scripted setups or external REPL frontends
* Configurable mux port (`-p`), log level (`-l`), and log file

**Internal:**
* CI/CD via GitHub Actions: Python 3.14 test matrix, trusted publisher workflow for PyPI releases
* 114 tests covering protocol framing, sequence rewriting, multi-client routing, late-join state replay, and the IPython extension
