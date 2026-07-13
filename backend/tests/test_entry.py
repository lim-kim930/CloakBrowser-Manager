"""Tests for the argparse entry point and stdin watchdog."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend import database as db, main


@pytest.fixture(autouse=True)
def _isolate_entry_side_effects(monkeypatch):
    """main() mutates db globals, ALLOWED_ORIGINS, _uvicorn_server, and env —
    snapshot everything so each test starts clean and leaks nothing."""
    monkeypatch.setattr(db, "DATA_DIR", db.DATA_DIR)
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)
    monkeypatch.setattr(main, "ALLOWED_ORIGINS", list(main.DEFAULT_ALLOWED_ORIGINS))
    monkeypatch.setattr(main, "_uvicorn_server", None)
    # setenv first (captures the original value for restore), then clear it
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", os.environ.get("CLOAKBROWSER_CACHE_DIR", ""))
    monkeypatch.delenv("CLOAKBROWSER_CACHE_DIR", raising=False)


# ── build_arg_parser ─────────────────────────────────────────────────────────


def test_parser_defaults():
    args = main.build_arg_parser().parse_args([])
    assert args.port == 8000
    assert args.host == "127.0.0.1"
    assert args.data_dir is None
    assert args.allow_origin == []


def test_parser_custom_values(tmp_path: Path):
    args = main.build_arg_parser().parse_args([
        "--port", "9000",
        "--host", "0.0.0.0",
        "--data-dir", str(tmp_path),
        "--allow-origin", "http://a.example",
        "--allow-origin", "http://b.example",
    ])
    assert args.port == 9000
    assert args.host == "0.0.0.0"
    assert args.data_dir == tmp_path
    assert args.allow_origin == ["http://a.example", "http://b.example"]


# ── main() wiring ────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_uvicorn(monkeypatch):
    created = {}

    class FakeServer:
        def __init__(self, config):
            created["config"] = config
            self.should_exit = False

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(main.uvicorn, "Server", FakeServer)
    return created


def test_main_configures_everything(fake_uvicorn, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "_start_stdin_watchdog", MagicMock())

    data_dir = tmp_path / "appdata"
    main.main(["--port", "8123", "--data-dir", str(data_dir), "--allow-origin", "http://x.example"])

    assert fake_uvicorn["ran"] is True
    assert fake_uvicorn["config"].port == 8123
    assert fake_uvicorn["config"].host == "127.0.0.1"
    assert db.DB_PATH == data_dir / "profiles.db"
    assert os.environ["CLOAKBROWSER_CACHE_DIR"] == str(data_dir / "chromium-cache")
    assert "http://x.example" in main.ALLOWED_ORIGINS
    assert main._uvicorn_server is not None


def test_main_respects_existing_cache_dir_env(fake_uvicorn, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "_start_stdin_watchdog", MagicMock())
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", "C:/custom-cache")
    main.main(["--data-dir", str(tmp_path)])
    assert os.environ["CLOAKBROWSER_CACHE_DIR"] == "C:/custom-cache"


def test_main_starts_watchdog_only_in_sidecar_mode(fake_uvicorn, monkeypatch, tmp_path: Path):
    watchdog = MagicMock()
    monkeypatch.setattr(main, "_start_stdin_watchdog", watchdog)
    main.main(["--data-dir", str(tmp_path)])  # no --port → not sidecar mode
    watchdog.assert_not_called()
    main.main(["--port", "8124", "--data-dir", str(tmp_path)])  # --port → sidecar
    watchdog.assert_called_once()


# ── stdin watchdog ───────────────────────────────────────────────────────────


def test_stdin_watchdog_triggers_shutdown_on_eof(monkeypatch):
    class FakeBuffer:
        def read(self, n):
            return b""  # immediate EOF

    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(buffer=FakeBuffer()))
    called = []
    monkeypatch.setattr(main, "request_shutdown", lambda: called.append(True))
    main._stdin_watchdog()
    assert called == [True]


def test_stdin_watchdog_survives_read_errors(monkeypatch):
    class FakeBuffer:
        def read(self, n):
            raise OSError("stdin gone")

    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(buffer=FakeBuffer()))
    called = []
    monkeypatch.setattr(main, "request_shutdown", lambda: called.append(True))
    main._stdin_watchdog()
    assert called == [True]
