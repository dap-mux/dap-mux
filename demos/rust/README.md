# Rust Demo: Dijkstra's Shortest Path

Demonstrates dap-mux with a Rust debug adapter (codelldb) and
[dap-observer](https://github.com/shaleh/dap-observer), a read-only terminal
UI that watches variables in the current stack frame.

The debug target is a Dijkstra implementation on a small hardcoded graph.
The `dist`, `prev`, and `heap` variables evolve visibly on every iteration,
making this a good showcase for dap-observer's variable tree.

## Prerequisites

* [`codelldb`](https://github.com/vadimcn/codelldb) — the Rust/C/C++ debug
  adapter
* [`dap-observer`](https://github.com/shaleh/dap-observer) — the variable
  watcher
* Helix with the `rust` debugger block configured in `languages.toml` (see
  `demos/helix/` for the Python equivalent; the Rust block uses
  `transport = "tcp"` with no `command`/`args`)

## Running a session

**1. Build the binary:**

```
cd demos/rust
cargo build
```

**2. Start codelldb in server mode (Terminal 1):**

```
codelldb --port 5678
```

**3. Start dap-mux in headless attach mode (Terminal 2):**

```
dmux --attach 5678 --headless -p 5679
```

**4. Start dap-observer (Terminal 3):**

```
dap-observer
```

It connects to `127.0.0.1:5679` by default and waits. The variable tree
populates each time execution stops at a breakpoint.

**5. Set breakpoints in Helix, then connect:**

Open `demos/rust/src/main.rs` in Helix. Set a breakpoint on the
`heap.pop()` line (`<space>b`). Then connect to dap-mux:

```
:debug-remote 127.0.0.1:5679 launch
```

Helix prompts for the binary path:

```
binary: demos/rust/target/debug/dijkstra
```

Execution starts and pauses at your breakpoint. dap-observer's variable tree
shows the current frame's locals. Step with `<space>c` (continue) or your
configured step keys; dap-observer refreshes on every stop.

## Good breakpoint targets

| Location | What to watch |
|---|---|
| Top of `shortest_path` | `dist`, `prev`, `heap` all empty — baseline |
| `heap.pop()` line | `cost`, `node` update each iteration; watch `dist` grow |
| `if node == goal` branch | `path` being reconstructed; `prev` chain |
| Inner `for (next, weight)` loop | `next_cost` vs current `dist` entry — relaxation in action |

## dap-observer tips

* Press `w` on any variable to pin it as a watch — it stays visible at the
  top across frames and shows `(unavailable)` when out of scope.
* Navigate the tree with `j`/`k`; expand/collapse with `l`/`h` or `Enter`.
* `q` or `Esc` disconnects cleanly.
