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

_mock_download = types.ModuleType("cloakbrowser.download")
_mock_download.ensure_binary = MagicMock()  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)
sys.modules.setdefault("cloakbrowser.download", _mock_download)
_mock_cloakbrowser.config = _mock_config  # type: ignore[attr-defined]
_mock_cloakbrowser.download = _mock_download  # type: ignore[attr-defined]


from backend import database as db  # noqa: E402


@pytest.fixture()
def installed_kernel(tmp_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Register a valid kernel: cache dir + fake exe + DB row (default)."""
    from backend import kernel_manager as km

    cache = tmp_path / "kernel-cache"
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(cache))
    exe = km.kernel_exe("1.0.0.0")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake")
    return db.create_kernel("1.0.0.0", "downloaded")


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


@pytest.fixture()
def app_client(tmp_db: Path, installed_kernel, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB, ready kernel, and no real cleanup."""
    from backend import main

    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
