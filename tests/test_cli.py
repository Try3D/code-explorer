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
def mock_deps(mocker, monkeypatch, tmp_path):
    """Mock all external dependencies so main() runs in isolation."""
    # Isolate config loading
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH", tmp_path / "nope.jsonc")
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH_JSON", tmp_path / "nope.json")

    mocks = {
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
            return_value="The answer is 42.",
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
