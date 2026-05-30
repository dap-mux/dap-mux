"""
Fibonacci demo for dap-mux.

Set breakpoints on compute() or the loop in main() to watch the multiplexer
distribute DAP events across multiple clients simultaneously.
"""

import time


def compute(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed)."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def main() -> None:
    """Run the Fibonacci sequence until interrupted."""
    print("Fibonacci sequence (Ctrl-C to stop)\n")
    i = 0
    while True:
        result = compute(i)
        print(f"  fib({i:3d}) = {result}")
        time.sleep(0.5)
        i += 1


if __name__ == "__main__":
    main()
