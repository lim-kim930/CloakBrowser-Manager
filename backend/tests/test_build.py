"""Tests for the PyInstaller build helper (pure functions only)."""

from __future__ import annotations

import pytest

from backend.build import MAX_SIDECAR_BYTES, check_sidecar_size, target_triple


def test_target_triple_shape():
    triple = target_triple()
    # e.g. x86_64-pc-windows-msvc / aarch64-apple-darwin / x86_64-unknown-linux-gnu
    parts = triple.split("-")
    assert len(parts) >= 3
    assert parts[0] in ("x86_64", "aarch64")


def test_check_sidecar_size_under_limit_passes():
    # ~60MB real backend and the limit boundary itself are allowed.
    check_sidecar_size(60 * 1024 * 1024)
    check_sidecar_size(MAX_SIDECAR_BYTES)


def test_check_sidecar_size_over_limit_raises():
    # A kernel-inclusive artifact (150MB+) must be rejected with a license note.
    with pytest.raises(SystemExit) as exc:
        check_sidecar_size(MAX_SIDECAR_BYTES + 1)
    assert "BINARY-LICENSE" in str(exc.value)
