"""Tests for code_explorer.cli (the CLI entry point).

Tests verify argument parsing, config override logic, error handling,
and output behavior — all with mocked dependencies to avoid real git/subprocess ops.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code_explorer.cli import main


@pytest.fixture
def mock_store(mocker):
    """Return a mock SessionStore instance injected into cli.SessionStore()."""
    store = MagicMock()
    store.get.return_value = None  # no existing session by default
    mocker.patch("code_explorer.cli.SessionStore", return_value=store)
    return store


@pytest.fixture
def mock_deps(mocker, monkeypatch, mock_store, tmp_path):
    """Mock all external dependencies so main() runs in isolation."""
    # Isolate config loading
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH", tmp_path / "nope.jsonc")
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH_JSON", tmp_path / "nope.json")

    mocks = {
        "store": mock_store,
        "ensure_cache_dir": mocker.patch("code_explorer.cli.cfg_module.ensure_cache_dir"),
        "parse_git_url": mocker.patch(
            "code_explorer.cli.repo_manager.parse_git_url",
            return_value=("owner", "repo", Path("/tmp/repos/owner/repo"), "https://github.com/owner/repo.git"),
        ),
        "ensure_repo": mocker.patch(
            "code_explorer.cli.repo_manager.ensure_repo",
            return_value="main",
        ),
        "run_query": mocker.patch(
            "code_explorer.cli.cli_runner.run_query",
            return_value=("The answer is 42.", "sid-mock"),
        ),
    }
    return mocks


class TestCliSuccess:
    def test_happy_path_exits_zero(self, mock_deps, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "What is this?"])
        main()
        captured = capsys.readouterr()
        assert "The answer is 42." in captured.out

    def test_prints_repo_url(self, mock_deps, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "query"])
        main()
        assert "https://github.com/owner/repo" in capsys.readouterr().out

    def test_prints_query(self, mock_deps, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "my question"])
        main()
        assert "my question" in capsys.readouterr().out

    def test_prints_branch_when_provided(self, mock_deps, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", [
            "cexp", "https://github.com/owner/repo", "q", "--branch", "develop"
        ])
        main()
        out = capsys.readouterr().out
        assert "develop" in out

    def test_calls_ensure_cache_dir(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["ensure_cache_dir"].assert_called_once()

    def test_calls_parse_git_url_with_repo(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["parse_git_url"].assert_called_once_with("https://github.com/owner/repo")

    def test_calls_run_query_with_question(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "my question"])
        main()
        args = mock_deps["run_query"].call_args[0]
        assert args[0] == "my question"


class TestCliConfigOverrides:
    def test_cli_flag_overrides_config(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "cexp", "https://github.com/owner/repo", "q", "--cli", "opencode"
        ])
        main()
        config = mock_deps["run_query"].call_args[0][2]
        assert config["cli"] == "opencode"

    def test_model_flag_overrides_config(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "cexp", "https://github.com/owner/repo", "q", "--model", "opus"
        ])
        main()
        config = mock_deps["run_query"].call_args[0][2]
        assert config["model"] == "opus"

    def test_max_turns_flag_overrides_config(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "cexp", "https://github.com/owner/repo", "q", "--max-turns", "5"
        ])
        main()
        config = mock_deps["run_query"].call_args[0][2]
        assert config["max_turns"] == 5

    def test_no_flags_uses_defaults(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        config = mock_deps["run_query"].call_args[0][2]
        assert config["cli"] == "claude"
        assert config["model"] == "haiku"

    def test_branch_passed_to_ensure_repo(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "cexp", "https://github.com/owner/repo", "q", "--branch", "develop"
        ])
        main()
        kwargs_or_args = mock_deps["ensure_repo"].call_args
        # branch is the 5th positional arg
        assert kwargs_or_args[0][4] == "develop"


class TestCliErrorHandling:
    def test_invalid_url_exits_1(self, mock_deps, monkeypatch, capsys):
        mock_deps["parse_git_url"].side_effect = ValueError("Invalid Git URL")
        monkeypatch.setattr(sys, "argv", ["cexp", "bad-url", "q"])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "Invalid Git URL" in capsys.readouterr().err

    def test_clone_failure_exits_1(self, mock_deps, monkeypatch, capsys):
        mock_deps["ensure_repo"].side_effect = RuntimeError("Repository not found")
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "Repository not found" in capsys.readouterr().err

    def test_query_failure_exits_1(self, mock_deps, monkeypatch, capsys):
        mock_deps["run_query"].side_effect = RuntimeError("claude CLI not found")
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "claude CLI not found" in capsys.readouterr().err

    def test_missing_required_args_exits_2(self, monkeypatch):
        """argparse exits with code 2 when required args are missing."""
        monkeypatch.setattr(sys, "argv", ["cexp"])
        with pytest.raises(SystemExit, match="2"):
            main()


class TestCliSessionBehavior:
    def test_new_session_prints_new(self, mock_deps, monkeypatch, capsys):
        mock_deps["store"].get.return_value = None
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        assert "session: new" in capsys.readouterr().out

    def test_resumed_session_prints_session_id(self, mock_deps, monkeypatch, capsys):
        mock_deps["store"].get.return_value = "abc-123"
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        assert "session: resuming abc-123" in capsys.readouterr().out

    def test_session_id_passed_to_run_query_when_resuming(self, mock_deps, monkeypatch):
        mock_deps["store"].get.return_value = "abc-123"
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        assert mock_deps["run_query"].call_args[1]["session_id"] == "abc-123"

    def test_no_session_id_passed_to_run_query_when_new(self, mock_deps, monkeypatch):
        mock_deps["store"].get.return_value = None
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        assert mock_deps["run_query"].call_args[1]["session_id"] is None

    def test_session_saved_after_success(self, mock_deps, monkeypatch):
        mock_deps["run_query"].return_value = ("answer", "new-sid-456")
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["store"].save.assert_called_once_with("owner/repo@main", "new-sid-456")

    def test_session_not_saved_when_session_id_empty(self, mock_deps, monkeypatch):
        mock_deps["run_query"].return_value = ("answer", "")
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["store"].save.assert_not_called()

    def test_session_key_uses_owner_repo_branch(self, mock_deps, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["store"].get.assert_called_once_with("owner/repo@main")

    def test_stale_session_cleared_and_retried_on_failure(self, mock_deps, monkeypatch, capsys):
        mock_deps["store"].get.return_value = "stale-sid"
        mock_deps["run_query"].side_effect = [
            RuntimeError("session not found"),
            ("fresh answer", "new-sid"),
        ]
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["store"].clear.assert_called_once_with("owner/repo@main")
        assert mock_deps["run_query"].call_count == 2
        # second call has no session_id
        assert mock_deps["run_query"].call_args_list[1][1].get("session_id") is None

    def test_stale_session_retry_saves_new_session(self, mock_deps, monkeypatch):
        mock_deps["store"].get.return_value = "stale-sid"
        mock_deps["run_query"].side_effect = [
            RuntimeError("expired"),
            ("answer", "brand-new-sid"),
        ]
        monkeypatch.setattr(sys, "argv", ["cexp", "https://github.com/owner/repo", "q"])
        main()
        mock_deps["store"].save.assert_called_once_with("owner/repo@main", "brand-new-sid")
