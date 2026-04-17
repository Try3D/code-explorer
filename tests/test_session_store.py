"""Tests for code_explorer.session_store.SessionStore."""

import json
from pathlib import Path

import pytest

from code_explorer.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(path=tmp_path / "sessions.json")


class TestSessionStoreGet:
    def test_returns_none_for_missing_key(self, store):
        assert store.get("owner/repo@main") is None

    def test_returns_none_when_file_absent(self, store):
        assert store.get("any/key@branch") is None

    def test_returns_stored_session_id(self, store):
        store.save("owner/repo@main", "sid-abc")
        assert store.get("owner/repo@main") == "sid-abc"

    def test_returns_none_for_different_key(self, store):
        store.save("owner/repo@main", "sid-abc")
        assert store.get("owner/repo@dev") is None


class TestSessionStoreSave:
    def test_creates_file_on_first_save(self, store):
        store.save("owner/repo@main", "sid1")
        assert store._path.exists()

    def test_save_and_get_roundtrip(self, store):
        store.save("o/r@b", "mysid")
        assert store.get("o/r@b") == "mysid"

    def test_overwrite_existing_session(self, store):
        store.save("o/r@b", "old")
        store.save("o/r@b", "new")
        assert store.get("o/r@b") == "new"

    def test_multiple_keys_independent(self, store):
        store.save("o/r@main", "sid1")
        store.save("o/r@dev", "sid2")
        assert store.get("o/r@main") == "sid1"
        assert store.get("o/r@dev") == "sid2"

    def test_persists_last_used_at(self, store):
        store.save("o/r@b", "sid")
        data = json.loads(store._path.read_text())
        assert "last_used_at" in data["o/r@b"]


class TestSessionStoreClear:
    def test_clear_removes_key(self, store):
        store.save("o/r@b", "sid")
        store.clear("o/r@b")
        assert store.get("o/r@b") is None

    def test_clear_missing_key_is_noop(self, store):
        store.clear("nonexistent/key@branch")  # should not raise

    def test_clear_leaves_other_keys(self, store):
        store.save("o/r@main", "s1")
        store.save("o/r@dev", "s2")
        store.clear("o/r@main")
        assert store.get("o/r@dev") == "s2"


class TestSessionStoreCorruption:
    def test_corrupt_file_returns_none(self, tmp_path):
        path = tmp_path / "sessions.json"
        path.write_text("not valid json", encoding="utf-8")
        store = SessionStore(path=path)
        assert store.get("any/key@b") is None

    def test_corrupt_file_recovers_on_save(self, tmp_path):
        path = tmp_path / "sessions.json"
        path.write_text("not valid json", encoding="utf-8")
        store = SessionStore(path=path)
        store.save("o/r@b", "sid")
        assert store.get("o/r@b") == "sid"
