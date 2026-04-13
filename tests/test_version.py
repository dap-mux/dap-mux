"""Smoke test to verify the package is importable."""

from __future__ import annotations

import dap_mux


def test_version_is_string() -> None:
    """The package exposes a version string."""
    assert isinstance(dap_mux.__version__, str)
