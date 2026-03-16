"""Tests for code_explorer.config.

Think about config from a user's perspective:
- What guarantees should the config system provide?
- What edge cases exist in config file loading?
- What invariants should always hold?
"""

import logging
from pathlib import Path

import pytest

from code_explorer.config import (
    DEFAULTS,
    ensure_cache_dir,
    get_repos_dir,
    load_config,
    setup_logging,
)


# ---------------------------------------------------------------------------
# DEFAULTS invariants
# ---------------------------------------------------------------------------


class TestDefaults:
    """The DEFAULTS dict is the contract for what config keys exist."""

    def test_has_all_required_keys(self):
        required = {"cli", "model", "allowed_tools", "max_turns", "repos_dir"}
        assert required <= set(DEFAULTS)

    def test_cli_is_string(self):
        assert isinstance(DEFAULTS["cli"], str)

    def test_model_is_string(self):
        assert isinstance(DEFAULTS["model"], str)

    def test_allowed_tools_is_list_of_strings(self):
        assert isinstance(DEFAULTS["allowed_tools"], list)
        assert all(isinstance(t, str) for t in DEFAULTS["allowed_tools"])

    def test_max_turns_is_positive_int(self):
        assert isinstance(DEFAULTS["max_turns"], int)
        assert DEFAULTS["max_turns"] > 0

    def test_repos_dir_is_string(self):
        assert isinstance(DEFAULTS["repos_dir"], str)

    def test_default_cli_is_claude(self):
        assert DEFAULTS["cli"] == "claude"


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config should merge user overrides onto defaults safely."""

    @pytest.fixture(autouse=True)
    def isolate_config_paths(self, monkeypatch, tmp_path):
        """Prevent tests from reading real ~/.code-explorer config."""
        self.tmp = tmp_path
        monkeypatch.setattr("code_explorer.config.CONFIG_PATH", tmp_path / "config.jsonc")
        monkeypatch.setattr("code_explorer.config.CONFIG_PATH_JSON", tmp_path / "config.json")

    def test_returns_defaults_when_no_config_file(self):
        result = load_config()
        assert result == DEFAULTS

    def test_returns_fresh_copy_each_call(self):
        """Mutating the returned dict must not affect future calls."""
        first = load_config()
        first["cli"] = "mutated"
        second = load_config()
        assert second["cli"] == DEFAULTS["cli"]

    def test_does_not_mutate_defaults(self):
        original_cli = DEFAULTS["cli"]
        config = load_config()
        config["cli"] = "mutated"
        assert DEFAULTS["cli"] == original_cli

    def test_merges_jsonc_overrides(self):
        (self.tmp / "config.jsonc").write_text('{"cli": "opencode", "model": "gpt-4"}')
        result = load_config()
        assert result["cli"] == "opencode"
        assert result["model"] == "gpt-4"

    def test_unmentioned_defaults_survive_merge(self):
        (self.tmp / "config.jsonc").write_text('{"cli": "opencode"}')
        result = load_config()
        assert result["max_turns"] == DEFAULTS["max_turns"]
        assert result["allowed_tools"] == DEFAULTS["allowed_tools"]
        assert result["model"] == DEFAULTS["model"]
        assert result["repos_dir"] == DEFAULTS["repos_dir"]

    def test_falls_back_to_json_when_jsonc_missing(self):
        (self.tmp / "config.json").write_text('{"max_turns": 5}')
        result = load_config()
        assert result["max_turns"] == 5

    def test_jsonc_preferred_over_json(self):
        (self.tmp / "config.jsonc").write_text('{"cli": "opencode"}')
        (self.tmp / "config.json").write_text('{"cli": "claude"}')
        result = load_config()
        assert result["cli"] == "opencode"

    def test_extra_keys_in_file_are_passed_through(self):
        (self.tmp / "config.jsonc").write_text('{"custom_key": 42}')
        result = load_config()
        assert result["custom_key"] == 42

    def test_empty_config_file_returns_defaults(self):
        (self.tmp / "config.jsonc").write_text("{}")
        result = load_config()
        assert result == DEFAULTS

    def test_jsonc_comments_are_handled(self):
        """JSONC files may contain // and /* */ comments."""
        (self.tmp / "config.jsonc").write_text(
            '{\n'
            '  // This is a comment\n'
            '  "cli": "opencode"\n'
            '  /* block comment */\n'
            "}"
        )
        result = load_config()
        assert result["cli"] == "opencode"

    def test_config_can_override_every_default_key(self):
        (self.tmp / "config.jsonc").write_text(
            '{"cli": "opencode", "model": "opus", "allowed_tools": ["Read"],'
            ' "max_turns": 99, "repos_dir": "/custom/path"}'
        )
        result = load_config()
        assert result["cli"] == "opencode"
        assert result["model"] == "opus"
        assert result["allowed_tools"] == ["Read"]
        assert result["max_turns"] == 99
        assert result["repos_dir"] == "/custom/path"

    def test_override_list_replaces_entirely(self):
        """Setting allowed_tools in config replaces the default list, not appends."""
        (self.tmp / "config.jsonc").write_text('{"allowed_tools": ["Bash"]}')
        result = load_config()
        assert result["allowed_tools"] == ["Bash"]

    def test_config_with_null_value(self):
        """A null value in JSON should be preserved as None."""
        (self.tmp / "config.jsonc").write_text('{"model": null}')
        result = load_config()
        assert result["model"] is None


# ---------------------------------------------------------------------------
# get_repos_dir
# ---------------------------------------------------------------------------


class TestGetReposDir:
    def test_expands_tilde(self):
        result = get_repos_dir({"repos_dir": "~/some/path"})
        assert result.is_absolute()
        assert "~" not in str(result)

    def test_absolute_path_unchanged(self):
        result = get_repos_dir({"repos_dir": "/absolute/path"})
        assert result == Path("/absolute/path")

    def test_returns_path_type(self):
        result = get_repos_dir({"repos_dir": "/any/path"})
        assert isinstance(result, Path)

    def test_relative_path_stays_relative(self):
        result = get_repos_dir({"repos_dir": "relative/path"})
        assert str(result) == "relative/path"


# ---------------------------------------------------------------------------
# ensure_cache_dir
# ---------------------------------------------------------------------------


class TestEnsureCacheDir:
    def test_creates_directory(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "repos"
        ensure_cache_dir({"repos_dir": str(target)})
        assert target.is_dir()

    def test_idempotent(self, tmp_path):
        target = tmp_path / "repos"
        ensure_cache_dir({"repos_dir": str(target)})
        ensure_cache_dir({"repos_dir": str(target)})
        assert target.is_dir()

    def test_existing_dir_no_error(self, tmp_path):
        target = tmp_path / "repos"
        target.mkdir()
        ensure_cache_dir({"repos_dir": str(target)})


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_returns_logger_instance(self):
        result = setup_logging()
        assert isinstance(result, logging.Logger)

    def test_logger_name(self):
        result = setup_logging()
        assert result.name == "code_explorer"

    def test_idempotent_no_duplicate_handlers(self):
        """Calling setup_logging twice should not add duplicate handlers."""
        logger = setup_logging()
        handler_count = len(logger.handlers)
        setup_logging()
        assert len(logger.handlers) == handler_count

    def test_returns_same_logger_each_time(self):
        first = setup_logging()
        second = setup_logging()
        assert first is second
