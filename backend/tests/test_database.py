"""Tests for SQLite CRUD operations."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend import database as db


# ── configure ────────────────────────────────────────────────────────────────


def test_configure_sets_data_dir_and_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # configure() mutates module globals — snapshot current values so
    # monkeypatch restores them after the test (no cross-test pollution).
    monkeypatch.setattr(db, "DATA_DIR", db.DATA_DIR)
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)

    db.configure(tmp_path / "appdata")
    assert db.DATA_DIR == tmp_path / "appdata"
    assert db.DB_PATH == tmp_path / "appdata" / "profiles.db"
    # user_data_dir for new profiles derives from the configured DATA_DIR
    db.init_db()
    p = db.create_profile("Cfg")
    assert p["user_data_dir"].startswith(str(tmp_path / "appdata"))


# ── init_db ──────────────────────────────────────────────────────────────────


def test_init_db_creates_tables(tmp_db: Path):
    with db.get_db() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in tables}
    assert "profiles" in names
    assert "profile_tags" in names


def test_init_db_idempotent(tmp_db: Path):
    # Second call should not crash
    db.init_db()
    with db.get_db() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert len(tables) >= 2


# ── create_profile ───────────────────────────────────────────────────────────


def test_create_profile_minimal(tmp_db: Path):
    p = db.create_profile("Test")
    assert p["name"] == "Test"
    assert isinstance(p["id"], str) and len(p["id"]) == 36  # UUID
    assert 10000 <= p["fingerprint_seed"] <= 99999  # random default
    assert p["user_data_dir"].startswith(str(tmp_db))
    assert p["platform"] == "windows"
    assert p["created_at"] is not None
    assert p["updated_at"] is not None


def test_create_profile_with_seed(tmp_db: Path):
    p = db.create_profile("Seeded", fingerprint_seed=42)
    assert p["fingerprint_seed"] == 42


def test_create_profile_all_fields(tmp_db: Path):
    p = db.create_profile(
        "Full",
        fingerprint_seed=99999,
        proxy="http://host:8080",
        timezone="America/New_York",
        locale="en-US",
        platform="macos",
        user_agent="Test UA",
        screen_width=2560,
        screen_height=1440,
        gpu_vendor="NVIDIA",
        gpu_renderer="RTX 3070",
        hardware_concurrency=16,
        humanize=True,
        human_preset="careful",
        headless=True,
        geoip=True,
        color_scheme="dark",
        notes="test note",
    )
    assert p["proxy"] == "http://host:8080"
    assert p["platform"] == "macos"
    assert p["gpu_vendor"] == "NVIDIA"
    assert p["hardware_concurrency"] == 16
    assert p["humanize"] == 1  # SQLite stores bool as int
    assert p["human_preset"] == "careful"
    assert p["color_scheme"] == "dark"


def test_create_profile_with_tags(tmp_db: Path):
    p = db.create_profile(
        "Tagged",
        tags=[
            {"tag": "work", "color": "#ff0000"},
            {"tag": "dev", "color": "#00ff00"},
        ],
    )
    assert len(p["tags"]) == 2
    tag_names = {t["tag"] for t in p["tags"]}
    assert tag_names == {"work", "dev"}


def test_create_profile_defaults(tmp_db: Path):
    p = db.create_profile("Defaults")
    assert p["platform"] == "windows"
    assert p["screen_width"] == 1920
    assert p["screen_height"] == 1080
    assert p["humanize"] == 0
    assert p["headless"] == 0
    assert p["geoip"] == 0
    assert p["human_preset"] == "default"
    assert p["launch_args"] == []


def test_create_profile_with_launch_args(tmp_db: Path):
    p = db.create_profile("WithArgs", launch_args=["--load-extension=/tmp/ext", "--disable-features=Foo"])
    assert p["launch_args"] == ["--load-extension=/tmp/ext", "--disable-features=Foo"]


def test_get_profile_launch_args_roundtrip(tmp_db: Path):
    p = db.create_profile("Args", launch_args=["--flag1", "--flag2"])
    fetched = db.get_profile(p["id"])
    assert fetched["launch_args"] == ["--flag1", "--flag2"]


def test_update_profile_launch_args(tmp_db: Path):
    p = db.create_profile("Args")
    assert p["launch_args"] == []
    updated = db.update_profile(p["id"], launch_args=["--new-flag"])
    assert updated["launch_args"] == ["--new-flag"]


def test_update_profile_launch_args_none_becomes_empty(tmp_db: Path):
    p = db.create_profile("Args", launch_args=["--flag"])
    updated = db.update_profile(p["id"], launch_args=None)
    assert updated["launch_args"] == []


def test_list_profiles_includes_launch_args(tmp_db: Path):
    db.create_profile("A", launch_args=["--arg1"])
    db.create_profile("B")
    profiles = db.list_profiles()
    args_by_name = {p["name"]: p["launch_args"] for p in profiles}
    assert args_by_name["A"] == ["--arg1"]
    assert args_by_name["B"] == []


# ── get_profile ──────────────────────────────────────────────────────────────


def test_get_profile_exists(sample_profile: dict):
    p = db.get_profile(sample_profile["id"])
    assert p is not None
    assert p["name"] == "Test Profile"
    assert p["fingerprint_seed"] == 12345


def test_get_profile_not_found(tmp_db: Path):
    assert db.get_profile("nonexistent") is None


def test_get_profile_includes_tags(tmp_db: Path):
    p = db.create_profile("Tagged", tags=[{"tag": "test", "color": "#aaa"}])
    fetched = db.get_profile(p["id"])
    assert len(fetched["tags"]) == 1
    assert fetched["tags"][0]["tag"] == "test"


# ── list_profiles ────────────────────────────────────────────────────────────


def test_list_profiles_empty(tmp_db: Path):
    assert db.list_profiles() == []


def test_list_profiles_ordered(tmp_db: Path):
    db.create_profile("First")
    time.sleep(0.01)  # ensure different timestamps
    db.create_profile("Second")
    profiles = db.list_profiles()
    assert len(profiles) == 2
    assert profiles[0]["name"] == "Second"  # newest first


def test_list_profiles_includes_tags(tmp_db: Path):
    db.create_profile("Tagged", tags=[{"tag": "x"}])
    profiles = db.list_profiles()
    assert len(profiles[0]["tags"]) == 1


# ── update_profile ───────────────────────────────────────────────────────────


def test_update_profile_partial(sample_profile: dict):
    updated = db.update_profile(sample_profile["id"], name="Renamed")
    assert updated["name"] == "Renamed"
    assert updated["fingerprint_seed"] == 12345  # unchanged


def test_update_profile_tags_replace(tmp_db: Path):
    p = db.create_profile("Tagged", tags=[{"tag": "old"}])
    updated = db.update_profile(p["id"], tags=[{"tag": "new", "color": "#fff"}])
    assert len(updated["tags"]) == 1
    assert updated["tags"][0]["tag"] == "new"


def test_update_profile_not_found(tmp_db: Path):
    assert db.update_profile("nonexistent", name="x") is None


def test_update_profile_no_fields(sample_profile: dict):
    # No-op update — profile should be unchanged
    updated = db.update_profile(sample_profile["id"])
    assert updated["name"] == sample_profile["name"]


def test_update_profile_updates_timestamp(sample_profile: dict):
    time.sleep(0.01)
    updated = db.update_profile(sample_profile["id"], name="New")
    assert updated["updated_at"] > sample_profile["created_at"]


# ── delete_profile ───────────────────────────────────────────────────────────


def test_delete_profile_exists(sample_profile: dict):
    assert db.delete_profile(sample_profile["id"]) is True
    assert db.get_profile(sample_profile["id"]) is None


def test_delete_profile_not_found(tmp_db: Path):
    assert db.delete_profile("nonexistent") is False


def test_delete_profile_cascades_tags(tmp_db: Path):
    p = db.create_profile("Tagged", tags=[{"tag": "a"}, {"tag": "b"}])
    db.delete_profile(p["id"])
    # Verify tags are gone
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profile_tags WHERE profile_id = ?", (p["id"],)
        ).fetchall()
    assert len(rows) == 0


# ── default_data_dir / lazy configure ────────────────────────────────────────


def test_default_data_dir_is_cloakbrowser_dir():
    d = db.default_data_dir()
    assert d.is_absolute()
    assert d.name == "CloakBrowser"


def test_lazy_auto_configure(tmp_path: Path, monkeypatch):
    """Without configure(), first DB access falls back to default_data_dir()."""
    monkeypatch.setattr(db, "DATA_DIR", None)
    monkeypatch.setattr(db, "DB_PATH", None)
    monkeypatch.setattr(db, "default_data_dir", lambda: tmp_path / "auto")
    db.init_db()
    assert (tmp_path / "auto" / "profiles.db").exists()


# ── Kernels ───────────────────────────────────────────────────────────────────


class TestKernels:
    def test_create_first_kernel_becomes_default(self, tmp_db):
        k = db.create_kernel("146.0.7680.177.5", "downloaded")
        assert k["version"] == "146.0.7680.177.5"
        assert k["source"] == "downloaded"
        assert k["source_path"] is None
        assert k["is_default"] is True

    def test_second_kernel_not_default(self, tmp_db):
        db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "imported", source_path=r"D:\kernels\two")
        assert k2["is_default"] is False
        assert k2["source_path"] == r"D:\kernels\two"

    def test_duplicate_version_rejected(self, tmp_db):
        import sqlite3
        db.create_kernel("1.0.0.0", "downloaded")
        with pytest.raises(sqlite3.IntegrityError):
            db.create_kernel("1.0.0.0", "imported", source_path="x")

    def test_list_kernels_profile_count(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        db.create_profile(name="P1", kernel_id=k["id"])
        db.create_profile(name="P2", kernel_id=k["id"])
        db.create_profile(name="P3")  # follows default, does not count as reference
        kernels = db.list_kernels()
        assert len(kernels) == 1
        assert kernels[0]["profile_count"] == 2

    def test_set_default_kernel_moves_flag(self, tmp_db):
        k1 = db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "downloaded")
        assert db.set_default_kernel(k2["id"]) is True
        assert db.get_default_kernel()["id"] == k2["id"]
        assert db.get_kernel(k1["id"])["is_default"] is False

    def test_set_default_unknown_id(self, tmp_db):
        assert db.set_default_kernel("nope") is False

    def test_delete_kernel_reassigns_default(self, tmp_db):
        k1 = db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "downloaded")
        assert db.delete_kernel(k1["id"]) is True
        assert db.get_default_kernel()["id"] == k2["id"]

    def test_delete_kernel_nulls_profile_reference(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        p = db.create_profile(name="P", kernel_id=k["id"])
        db.delete_kernel(k["id"])
        assert db.get_profile(p["id"])["kernel_id"] is None

    def test_profile_kernel_id_roundtrip(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        p = db.create_profile(name="P", kernel_id=k["id"])
        assert p["kernel_id"] == k["id"]
        p2 = db.update_profile(p["id"], kernel_id=None)
        assert p2["kernel_id"] is None
