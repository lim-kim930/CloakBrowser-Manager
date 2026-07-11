"""Shared test fixtures for backend tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock cloakbrowser BEFORE any backend module is imported.
# browser_manager.py does `from cloakbrowser import launch_persistent_context_async`
# at module level, and main.py imports BrowserManager which triggers it.
# main.py:381 also does `from cloakbrowser.config import CHROMIUM_VERSION`.
# ---------------------------------------------------------------------------

_mock_cloakbrowser = types.ModuleType("cloakbrowser")
_mock_cloakbrowser.launch_persistent_context_async = AsyncMock()  # type: ignore[attr-defined]

_mock_config = types.ModuleType("cloakbrowser.config")
_mock_config.CHROMIUM_VERSION = "0.0.0-test"  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)

_mock_download = types.ModuleType("cloakbrowser.download")
_mock_download.ensure_binary = MagicMock(return_value="/fake/chrome")  # type: ignore[attr-defined]
sys.modules.setdefault("cloakbrowser.download", _mock_download)


from backend import database as db  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database module at a temp directory and init schema."""
    db_file = tmp_path / "profiles.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()
    return tmp_path


@pytest.fixture()
def sample_profile(tmp_db: Path):
    """Create and return a sample profile dict."""
    return db.create_profile(name="Test Profile", fingerprint_seed=12345)


@pytest.fixture(autouse=True)
def _reset_binary_mgr():
    """Reset the binary_mgr singleton between tests.

    Each TestClient lifespan runs on a fresh event loop. Without a reset the
    module-level singleton keeps ready=True plus a _task bound to a prior
    test's (now closed) loop, so wait_ready() in later lifespans raises
    'ValueError: The future belongs to a different loop' as background noise.
    Autouse covers app_client here and test_auth.py's client fixtures alike.
    """
    main = sys.modules.get("backend.main")
    if main is not None:
        main.binary_mgr.ready = False
        main.binary_mgr.downloading = False
        main.binary_mgr.error = None
        main.binary_mgr._task = None
    yield


@pytest.fixture()
def app_client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB and browser manager."""
    from backend import main

    # Patch lifespan-called methods to avoid subprocess calls (pkill, Xvnc)
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
