"""Tests for the PyInstaller build helper (pure functions only)."""

from __future__ import annotations

from backend.build import target_triple


def test_target_triple_shape():
    triple = target_triple()
    # e.g. x86_64-pc-windows-msvc / aarch64-apple-darwin / x86_64-unknown-linux-gnu
    parts = triple.split("-")
    assert len(parts) >= 3
    assert parts[0] in ("x86_64", "aarch64")
