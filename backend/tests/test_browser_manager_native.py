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
    monkeypatch.setattr(bm, "resolve_kernel_version", lambda v: "146.0.7680.177.5")

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
    # Native always launches a pinned, verified kernel
    assert kwargs["browser_version"] == "146.0.7680.177.5"
    assert running.kernel_version == "146.0.7680.177.5"


@pytest.mark.asyncio
async def test_native_launch_passes_profile_kernel_to_resolver(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: False)
    seen: list[str | None] = []

    def fake_resolve(explicit):
        seen.append(explicit)
        return "148.0.7778.215.2"

    monkeypatch.setattr(bm, "resolve_kernel_version", fake_resolve)
    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    profile = {
        "id": "p2",
        "user_data_dir": str(tmp_path / "p2"),
        "kernel_version": "148.0.7778.215.2",
    }
    await mgr.launch(profile)
    assert seen == ["148.0.7778.215.2"]
    assert fake_launch.call_args.kwargs["browser_version"] == "148.0.7778.215.2"


@pytest.mark.asyncio
async def test_native_launch_without_kernel_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: False)
    monkeypatch.setattr(bm, "resolve_kernel_version", lambda v: None)
    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    profile = {"id": "p3", "user_data_dir": str(tmp_path / "p3")}
    with pytest.raises(ValueError, match="No browser kernel is installed"):
        await mgr.launch(profile)
    fake_launch.assert_not_called()
    # Nothing left half-launched
    assert "p3" not in mgr._launching
    assert "p3" not in mgr.running


@pytest.mark.asyncio
async def test_vnc_launch_without_pin_stays_unpinned(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: True)
    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    mgr.vnc.allocate = AsyncMock(return_value=(1, 6001))
    mgr.vnc.start_vnc = AsyncMock()
    mgr.vnc.stop_vnc = AsyncMock()

    profile = {"id": "p4", "user_data_dir": str(tmp_path / "p4")}
    running = await mgr.launch(profile)

    # Exactly today's behavior: no version pin at all
    assert "browser_version" not in fake_launch.call_args.kwargs
    assert running.kernel_version is None


@pytest.mark.asyncio
async def test_vnc_launch_with_missing_pin_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: True)
    monkeypatch.setattr(bm, "kernel_installed", lambda v: False)
    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    mgr.vnc.allocate = AsyncMock(return_value=(1, 6001))
    mgr.vnc.start_vnc = AsyncMock()
    mgr.vnc.stop_vnc = AsyncMock()

    profile = {
        "id": "p5",
        "user_data_dir": str(tmp_path / "p5"),
        "kernel_version": "9.9.9.9",
    }
    with pytest.raises(ValueError, match="not installed"):
        await mgr.launch(profile)
    fake_launch.assert_not_called()
    mgr.vnc.allocate.assert_not_called()  # failed before any allocation


@pytest.mark.asyncio
async def test_vnc_launch_with_installed_pin_passes_it(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: True)
    monkeypatch.setattr(bm, "kernel_installed", lambda v: True)
    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    mgr.vnc.allocate = AsyncMock(return_value=(1, 6001))
    mgr.vnc.start_vnc = AsyncMock()
    mgr.vnc.stop_vnc = AsyncMock()

    profile = {
        "id": "p6",
        "user_data_dir": str(tmp_path / "p6"),
        "kernel_version": "146.0.7680.177.5",
    }
    running = await mgr.launch(profile)
    assert fake_launch.call_args.kwargs["browser_version"] == "146.0.7680.177.5"
    assert running.kernel_version == "146.0.7680.177.5"


def test_build_fingerprint_args_native_omits_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=True)
    assert "--use-angle=swiftshader" not in args
    assert "--fingerprint=7" in args


def test_build_fingerprint_args_vnc_keeps_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=False)
    assert "--use-angle=swiftshader" in args
