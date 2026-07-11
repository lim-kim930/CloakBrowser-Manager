"""Native-mode launch branch of BrowserManager."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import browser_manager as bm


def _make_context_mock():
    ctx = MagicMock()
    ctx.add_init_script = AsyncMock()
    ctx.pages = []
    ctx.on = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_native_launch_skips_vnc_and_display(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: False)

    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    mgr.vnc.allocate = AsyncMock()
    mgr.vnc.start_vnc = AsyncMock()

    profile = {
        "id": "p1",
        "user_data_dir": str(tmp_path / "p1"),
        "screen_width": 1440,
        "screen_height": 900,
    }
    running = await mgr.launch(profile)

    # VNC untouched
    mgr.vnc.allocate.assert_not_called()
    mgr.vnc.start_vnc.assert_not_called()
    assert running.display is None
    assert running.ws_port is None

    kwargs = fake_launch.call_args.kwargs
    # No DISPLAY injected
    assert "DISPLAY" not in kwargs.get("env", {})
    # Real GPU (no swiftshader), window sized to the profile
    assert "--use-angle=swiftshader" not in kwargs["args"]
    assert "--window-size=1440,900" in kwargs["args"]
    # No forced viewport in native mode
    assert kwargs.get("no_viewport") is True


def test_build_fingerprint_args_native_omits_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=True)
    assert "--use-angle=swiftshader" not in args
    assert "--fingerprint=7" in args


def test_build_fingerprint_args_vnc_keeps_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=False)
    assert "--use-angle=swiftshader" in args
