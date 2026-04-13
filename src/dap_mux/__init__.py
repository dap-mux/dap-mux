"""
DAP multiplexer for REPL-driven debugging with editor source tracking.

dap-mux sits between a debug adapter (like debugpy) and multiple DAP
clients (an editor and a REPL), letting you control debugging from an
IPython prompt while your editor follows along.

"""

from __future__ import annotations

from dap_mux.mux import Multiplexer

try:
    from dap_mux._version import __version__
except ModuleNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = (
    "Multiplexer",
    "__version__",
)
