"""_harden_stdio: third-party console writes must never crash a request.

The cloakbrowser package writes a promo banner containing "→" to sys.stderr
while resolving the kernel at launch. On a strict legacy-codepage stream that
raised UnicodeEncodeError — a ValueError, which the launch endpoint reported
in place of the launch — and the packaged windowed client has no stderr at all.
"""

from __future__ import annotations

import io
import sys

import pytest

from backend.main import _harden_stdio

PROMO_LINE = "  Try Pro free for 7 days → https://cloakbrowser.dev\n"


def test_strict_legacy_codepage_stream_no_longer_raises(monkeypatch: pytest.MonkeyPatch):
    buf = io.BytesIO()
    monkeypatch.setattr(
        sys, "stderr", io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    )
    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    )

    _harden_stdio()

    sys.stderr.write(PROMO_LINE)  # raised UnicodeEncodeError before the fix
    sys.stderr.flush()
    assert b"Try Pro free for 7 days" in buf.getvalue()
    assert b"\\u2192" in buf.getvalue()  # arrow preserved as an escape, not lost


def test_windowed_client_gets_stdio_sinks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    _harden_stdio()

    try:
        sys.stdout.write(PROMO_LINE)
        sys.stderr.write(PROMO_LINE)  # raised AttributeError before the fix
    finally:
        sys.stdout.close()
        sys.stderr.close()


def test_stream_without_reconfigure_is_tolerated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    _harden_stdio()  # StringIO has no reconfigure(); must not raise

    sys.stderr.write(PROMO_LINE)
