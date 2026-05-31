# Changelog

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
* Launch mode (`dmux script.py`) spawns debugpy and opens the IPython REPL in one command
* Attach mode (`dmux --attach host:port`) connects to an already-running debug adapter
* IPython extension with debug magics: `%step`, `%next`, `%continue_`, `%finish`, `%bt`, `%frame`, `%eval`, `%break`, `%clear`, `%sync`, `%connect`, `%disconnect`
* Headless mode (`--no-repl`) for scripted setups or external REPL frontends
* Configurable mux port (`-p`), log level (`-l`), and log file

**Internal:**
* CI/CD via GitHub Actions: Python 3.14 test matrix, trusted publisher workflow for PyPI releases
* 114 tests covering protocol framing, sequence rewriting, multi-client routing, late-join state replay, and the IPython extension
