# Demos

Live test material for dap-mux. Each demo uses `fibonacci.py` as the debug
target — a simple loop with an inner function, easy to set breakpoints on and
step through.

## fibonacci.py

Computes Fibonacci numbers in a loop, printing each result. Good breakpoint
targets: the top of `compute()` to watch recursive state, or the `print` line
in `main()` to stop between iterations.

## rust/

A Dijkstra's shortest path implementation as a Rust debug target. Demonstrates
dap-mux with codelldb and
[dap-observer](https://github.com/shaleh/dap-observer), a terminal UI variable
watcher. See `rust/README.md` for the full workflow.

## Running a session (Python/fibonacci)

**1. Start dap-mux with a pinned port:**

```
dmux demos/fibonacci.py -p 5679
```

The IPython prompt appears. The script is paused waiting for an editor to
connect and send `configurationDone`.

**2. Set breakpoints in your editor, then connect:**

* **VS Code** — copy `demos/vscode/launch.json` to `.vscode/launch.json` at
  the project root, open the project, set a breakpoint, then run the
  "Connect to dap-mux" configuration.

* **Helix** — merge `demos/helix/languages.toml` into
  `~/.config/helix/languages.toml`, open `demos/fibonacci.py`, set a
  breakpoint (`<space>b`), then connect:
  ```
  :debug-remote 127.0.0.1:5679 attach
  ```

**3. Step and evaluate from IPython:**

```python
%n          # step over
%s          # step into
%bt         # call stack
%eval i     # evaluate in the stopped frame
%c          # continue
```
