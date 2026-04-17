"""Tests for code_explorer.server (the MCP server tool).

Tests verify the code_explorer_query tool function's return structure,
error handling, and integration with internal modules — all mocked.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code_explorer.server import code_explorer_query


@pytest.fixture(autouse=True)
def mock_deps(mocker, monkeypatch, tmp_path):
    """Mock all external dependencies."""
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH", tmp_path / "nope.jsonc")
    monkeypatch.setattr("code_explorer.config.CONFIG_PATH_JSON", tmp_path / "nope.json")

    store = MagicMock()
    store.get.return_value = None
    mocker.patch("code_explorer.server._session_store", store)

    mocks = {
        "store": store,
        "ensure_cache_dir": mocker.patch("code_explorer.server.cfg_module.ensure_cache_dir"),
        "parse_git_url": mocker.patch(
            "code_explorer.server.repo_manager.parse_git_url",
            return_value=("owner", "repo", Path("/tmp/repos/owner/repo"), "https://github.com/owner/repo.git"),
        ),
        "ensure_repo": mocker.patch(
            "code_explorer.server.repo_manager.ensure_repo",
            return_value="main",
        ),
        "run_query": mocker.patch(
            "code_explorer.server.cli_runner.run_query",
            return_value=("The answer.", "sid-mock"),
        ),
    }
    return mocks


class TestSuccessResponse:
    def test_returns_dict(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert isinstance(result, dict)

    def test_has_answer_key(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["answer"] == "The answer."

    def test_has_repo_key(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["repo"] == "owner/repo"

    def test_has_branch_key(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["branch"] == "main"

    def test_has_cli_used_key(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["cli_used"] == "claude"

    def test_no_error_key_on_success(self, mock_deps):
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert "error" not in result

    def test_branch_arg_passed_through(self, mock_deps):
        code_explorer_query("https://github.com/owner/repo", "q", branch="develop")
        args = mock_deps["ensure_repo"].call_args[0]
        assert args[4] == "develop"

    def test_none_branch_by_default(self, mock_deps):
        code_explorer_query("https://github.com/owner/repo", "q")
        args = mock_deps["ensure_repo"].call_args[0]
        assert args[4] is None


class TestErrorResponse:
    def test_invalid_url_returns_error_dict(self, mock_deps):
        mock_deps["parse_git_url"].side_effect = ValueError("Invalid Git URL")
        result = code_explorer_query("bad-url", "q")
        assert "error" in result
        assert "Invalid Git URL" in result["error"]

    def test_clone_failure_returns_error_dict(self, mock_deps):
        mock_deps["ensure_repo"].side_effect = RuntimeError("Repository not found")
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert "error" in result
        assert "Repository not found" in result["error"]

    def test_query_failure_returns_error_dict(self, mock_deps):
        mock_deps["run_query"].side_effect = RuntimeError("claude CLI not found")
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert "error" in result
        assert "claude CLI not found" in result["error"]

    def test_error_response_has_no_answer_key(self, mock_deps):
        mock_deps["parse_git_url"].side_effect = ValueError("bad")
        result = code_explorer_query("bad", "q")
        assert "answer" not in result

    def test_error_response_is_dict(self, mock_deps):
        mock_deps["parse_git_url"].side_effect = ValueError("bad")
        result = code_explorer_query("bad", "q")
        assert isinstance(result, dict)


class TestServerSessionBehavior:
    def test_session_id_in_response(self, mock_deps):
        mock_deps["run_query"].return_value = ("answer", "sid-xyz")
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["session_id"] == "sid-xyz"

    def test_session_id_none_when_empty_string(self, mock_deps):
        mock_deps["run_query"].return_value = ("answer", "")
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert result["session_id"] is None

    def test_session_looked_up_before_run_query(self, mock_deps):
        mock_deps["store"].get.return_value = "prior-sid"
        code_explorer_query("https://github.com/owner/repo", "q")
        mock_deps["store"].get.assert_called_once_with("owner/repo@main")
        assert mock_deps["run_query"].call_args[1]["session_id"] == "prior-sid"

    def test_no_prior_session_passes_none(self, mock_deps):
        mock_deps["store"].get.return_value = None
        code_explorer_query("https://github.com/owner/repo", "q")
        assert mock_deps["run_query"].call_args[1]["session_id"] is None

    def test_session_saved_after_success(self, mock_deps):
        mock_deps["run_query"].return_value = ("answer", "new-sid-789")
        code_explorer_query("https://github.com/owner/repo", "q")
        mock_deps["store"].save.assert_called_once_with("owner/repo@main", "new-sid-789")

    def test_session_not_saved_when_empty(self, mock_deps):
        mock_deps["run_query"].return_value = ("answer", "")
        code_explorer_query("https://github.com/owner/repo", "q")
        mock_deps["store"].save.assert_not_called()

    def test_stale_session_cleared_and_retried(self, mock_deps):
        mock_deps["store"].get.return_value = "stale-sid"
        mock_deps["run_query"].side_effect = [
            RuntimeError("session expired"),
            ("fresh answer", "new-sid"),
        ]
        result = code_explorer_query("https://github.com/owner/repo", "q")
        mock_deps["store"].clear.assert_called_once_with("owner/repo@main")
        assert mock_deps["run_query"].call_count == 2
        assert result["answer"] == "fresh answer"

    def test_stale_session_retry_passes_no_session_id(self, mock_deps):
        mock_deps["store"].get.return_value = "stale-sid"
        mock_deps["run_query"].side_effect = [
            RuntimeError("expired"),
            ("answer", "new-sid"),
        ]
        code_explorer_query("https://github.com/owner/repo", "q")
        # second call must not pass the old session_id
        second_call_kwargs = mock_deps["run_query"].call_args_list[1][1]
        assert second_call_kwargs.get("session_id") is None

    def test_stale_session_second_failure_returns_error(self, mock_deps):
        mock_deps["store"].get.return_value = "stale-sid"
        mock_deps["run_query"].side_effect = [
            RuntimeError("session expired"),
            RuntimeError("agent crashed"),
        ]
        result = code_explorer_query("https://github.com/owner/repo", "q")
        assert "error" in result
        assert "agent crashed" in result["error"]
