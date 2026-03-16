"""Tests for code_explorer.cli_runner.

Three testable surfaces:
1. _wrap_query — pure string formatting
2. _extract_opencode_answer — pure NDJSON parsing
3. run_claude / run_opencode / run_query — subprocess orchestration (mocked)
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code_explorer.cli_runner import (
    _extract_opencode_answer,
    _wrap_query,
    run_claude,
    run_opencode,
    run_query,
)
from code_explorer.config import DEFAULTS


def _make_ndjson(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


def _make_successful_result(stdout: str = "answer") -> MagicMock:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = stdout
    mock.stderr = ""
    return mock


def _make_opencode_success(text: str = "ok") -> MagicMock:
    ndjson = _make_ndjson(
        {"type": "step_start"},
        {"type": "text", "part": {"type": "text", "text": text}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    )
    return _make_successful_result(ndjson)


# ===========================================================================
# _wrap_query
# ===========================================================================


class TestWrapQuery:
    def test_contains_cwd_path(self):
        result = _wrap_query("What is X?", Path("/some/repo"))
        assert "/some/repo" in result

    def test_contains_original_question(self):
        result = _wrap_query("What is X?", Path("/r"))
        assert "What is X?" in result

    def test_instructs_no_web_search(self):
        result = _wrap_query("q", Path("/r"))
        assert "Do NOT search the web" in result

    def test_returns_string(self):
        assert isinstance(_wrap_query("q", Path("/r")), str)

    def test_query_with_special_characters(self):
        query = 'What does `func("arg")` do?'
        result = _wrap_query(query, Path("/r"))
        assert query in result

    def test_query_with_newlines(self):
        query = "line1\nline2\nline3"
        result = _wrap_query(query, Path("/r"))
        assert query in result

    def test_empty_query(self):
        result = _wrap_query("", Path("/r"))
        assert isinstance(result, str)
        assert "/r" in result

    def test_cwd_with_spaces(self):
        result = _wrap_query("q", Path("/path with spaces/repo"))
        assert "/path with spaces/repo" in result


# ===========================================================================
# _extract_opencode_answer — core behavior
# ===========================================================================


class TestExtractOpencode:
    """Basic happy-path extraction."""

    def test_basic_stop_event(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "Hello world"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "Hello world"

    def test_concatenates_multiple_text_events(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "A"}},
            {"type": "text", "part": {"type": "text", "text": "B"}},
            {"type": "text", "part": {"type": "text", "text": "C"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "ABC"

    def test_uses_last_stop_segment(self):
        """When there are multiple stop-terminated segments, use the last one."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "first"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "Final answer"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "Final answer"

    def test_strips_leading_trailing_whitespace(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "  hello  "}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "hello"

    def test_preserves_internal_whitespace(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "line1\nline2\n  indented"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        result = _extract_opencode_answer(ndjson)
        assert "line1\nline2\n  indented" in result


class TestExtractOpencodeFiltering:
    """Events that should be ignored or handled specially."""

    def test_ignores_non_stop_finish(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "tool output"}},
            {"type": "step_finish", "part": {"reason": "tool_use"}},
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "real answer"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "real answer"

    def test_ignores_tool_use_events(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "tool_use", "part": {"name": "Bash", "input": "ls"}},
            {"type": "text", "part": {"type": "text", "text": "answer"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        result = _extract_opencode_answer(ndjson)
        assert result == "answer"
        assert "Bash" not in result

    def test_ignores_empty_text_events(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": ""}},
            {"type": "text", "part": {"type": "text", "text": "real"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "real"

    def test_stop_on_empty_segment_not_promoted(self):
        """step_start → step_finish(stop) with no text should not overwrite a prior segment."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "real answer"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
            {"type": "step_start"},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "real answer"

    def test_step_start_resets_accumulator(self):
        """Text from before a step_start should not leak into the next segment."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "old stuff"}},
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "fresh"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "fresh"


class TestExtractOpencodeFallbacks:
    """Edge cases and fallback behavior."""

    def test_empty_input(self):
        assert _extract_opencode_answer("") == ""

    def test_whitespace_only_input(self):
        assert _extract_opencode_answer("   \n  \n   ") == ""

    def test_fallback_to_current_segment_when_no_stop(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "partial"}},
        )
        assert _extract_opencode_answer(ndjson) == "partial"

    def test_skips_invalid_json_lines(self):
        ndjson = (
            "not json\n"
            + json.dumps({"type": "step_start"}) + "\n"
            + '{"broken"\n'
            + json.dumps({"type": "text", "part": {"type": "text", "text": "valid"}}) + "\n"
            + json.dumps({"type": "step_finish", "part": {"reason": "stop"}})
        )
        assert _extract_opencode_answer(ndjson) == "valid"

    def test_all_invalid_json_returns_raw_output(self):
        raw = "just plain text output"
        assert _extract_opencode_answer(raw) == raw

    def test_text_events_without_step_start(self):
        """Text events before any step_start should still be collected."""
        ndjson = _make_ndjson(
            {"type": "text", "part": {"type": "text", "text": "orphan"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "orphan"

    def test_missing_part_key_in_text_event(self):
        """Text event without 'part' should not crash."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text"},
            {"type": "text", "part": {"type": "text", "text": "ok"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "ok"

    def test_missing_text_key_in_part(self):
        """Part without 'text' key should not crash."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text"}},
            {"type": "text", "part": {"type": "text", "text": "ok"}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "ok"

    def test_missing_reason_in_step_finish(self):
        """step_finish without reason should not crash or be treated as stop."""
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "answer"}},
            {"type": "step_finish", "part": {}},
        )
        # Should fall back to current_segment since no stop reason
        assert _extract_opencode_answer(ndjson) == "answer"


class TestExtractOpencodeRealisticStreams:
    """Test with realistic multi-step agent conversations."""

    def test_tool_use_then_final_answer(self):
        """Typical pattern: agent uses tools, then gives final answer."""
        ndjson = _make_ndjson(
            # Step 1: agent reads a file
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "Let me read that file."}},
            {"type": "tool_use", "part": {"name": "Read", "input": "main.py"}},
            {"type": "step_finish", "part": {"reason": "tool_use"}},
            # Step 2: agent uses another tool
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "Let me check the tests."}},
            {"type": "tool_use", "part": {"name": "Grep", "input": "test_"}},
            {"type": "step_finish", "part": {"reason": "tool_use"}},
            # Step 3: final answer
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "The project uses pytest for testing."}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        assert _extract_opencode_answer(ndjson) == "The project uses pytest for testing."

    def test_multi_paragraph_answer(self):
        ndjson = _make_ndjson(
            {"type": "step_start"},
            {"type": "text", "part": {"type": "text", "text": "First paragraph.\n\n"}},
            {"type": "text", "part": {"type": "text", "text": "Second paragraph.\n\n"}},
            {"type": "text", "part": {"type": "text", "text": "Third paragraph."}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        )
        result = _extract_opencode_answer(ndjson)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        assert "Third paragraph" in result


# ===========================================================================
# run_query — dispatch logic
# ===========================================================================


class TestRunQueryDispatch:
    def test_dispatches_to_claude(self, mocker):
        mock = mocker.patch("code_explorer.cli_runner.run_claude", return_value="answer")
        result = run_query("q", Path("/r"), {"cli": "claude"})
        mock.assert_called_once_with("q", Path("/r"), {"cli": "claude"})
        assert result == "answer"

    def test_dispatches_to_opencode(self, mocker):
        mock = mocker.patch("code_explorer.cli_runner.run_opencode", return_value="answer")
        result = run_query("q", Path("/r"), {"cli": "opencode"})
        mock.assert_called_once()
        assert result == "answer"

    def test_unknown_cli_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown CLI backend"):
            run_query("q", Path("/r"), {"cli": "unknown"})

    def test_defaults_to_claude_when_cli_key_missing(self, mocker):
        mock = mocker.patch("code_explorer.cli_runner.run_claude", return_value="answer")
        run_query("q", Path("/r"), {})
        mock.assert_called_once()

    def test_passes_full_config_to_backend(self, mocker):
        config = {"cli": "claude", "model": "sonnet", "extra": True}
        mock = mocker.patch("code_explorer.cli_runner.run_claude", return_value="a")
        run_query("q", Path("/r"), config)
        _, _, passed_config = mock.call_args[0]
        assert passed_config is config


# ===========================================================================
# run_claude — subprocess orchestration
# ===========================================================================


class TestRunClaude:
    def test_success_returns_stripped_stdout(self, mocker):
        mocker.patch("subprocess.run", return_value=_make_successful_result("  answer  \n"))
        result = run_claude("q", Path("/r"), dict(DEFAULTS))
        assert result == "answer"

    def test_builds_correct_command(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_successful_result())
        config = {**DEFAULTS, "model": "sonnet", "max_turns": 10, "allowed_tools": ["Bash", "Read"]}
        run_claude("my question", Path("/repo"), config)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "sonnet"
        assert "--max-turns" in cmd
        idx = cmd.index("--max-turns")
        assert cmd[idx + 1] == "10"
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Bash,Read"
        assert "--output-format" in cmd

    def test_passes_cwd_to_subprocess(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_successful_result())
        run_claude("q", Path("/my/repo"), dict(DEFAULTS))
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == "/my/repo"

    def test_file_not_found_raises_runtime_error(self, mocker):
        mocker.patch("subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(RuntimeError, match="claude CLI not found"):
            run_claude("q", Path("/r"), dict(DEFAULTS))

    def test_timeout_raises_runtime_error(self, mocker):
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300),
        )
        with pytest.raises(RuntimeError, match="timed out"):
            run_claude("q", Path("/r"), dict(DEFAULTS))

    def test_nonzero_exit_raises_with_status(self, mocker):
        mock = MagicMock()
        mock.returncode = 1
        mock.stderr = "auth error"
        mock.stdout = ""
        mocker.patch("subprocess.run", return_value=mock)
        with pytest.raises(RuntimeError, match="status 1"):
            run_claude("q", Path("/r"), dict(DEFAULTS))

    def test_nonzero_exit_includes_stderr(self, mocker):
        mock = MagicMock()
        mock.returncode = 2
        mock.stderr = "bad credentials"
        mock.stdout = ""
        mocker.patch("subprocess.run", return_value=mock)
        with pytest.raises(RuntimeError, match="bad credentials"):
            run_claude("q", Path("/r"), dict(DEFAULTS))

    def test_nonzero_exit_no_stderr(self, mocker):
        mock = MagicMock()
        mock.returncode = 1
        mock.stderr = ""
        mock.stdout = ""
        mocker.patch("subprocess.run", return_value=mock)
        with pytest.raises(RuntimeError, match="status 1") as exc_info:
            run_claude("q", Path("/r"), dict(DEFAULTS))
        # Should not have a trailing colon when no stderr
        assert str(exc_info.value).endswith("status 1")

    def test_sets_timeout(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_successful_result())
        run_claude("q", Path("/r"), dict(DEFAULTS))
        kwargs = mock_run.call_args[1]
        assert kwargs["timeout"] == 300

    def test_captures_output(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_successful_result())
        run_claude("q", Path("/r"), dict(DEFAULTS))
        kwargs = mock_run.call_args[1]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True


# ===========================================================================
# run_opencode — subprocess orchestration
# ===========================================================================


class TestRunOpencode:
    def test_success_extracts_answer(self, mocker):
        mocker.patch("subprocess.run", return_value=_make_opencode_success("parsed"))
        result = run_opencode("q", Path("/r"), dict(DEFAULTS))
        assert result == "parsed"

    def test_qualifies_bare_model_name(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_opencode_success())
        run_opencode("q", Path("/r"), {**DEFAULTS, "model": "haiku"})
        cmd = mock_run.call_args[0][0]
        assert "anthropic/haiku" in cmd

    def test_leaves_qualified_model_name(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_opencode_success())
        run_opencode("q", Path("/r"), {**DEFAULTS, "model": "openai/gpt-4o"})
        cmd = mock_run.call_args[0][0]
        assert "openai/gpt-4o" in cmd
        assert "anthropic/openai/gpt-4o" not in cmd

    def test_model_with_slash_not_double_prefixed(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_opencode_success())
        run_opencode("q", Path("/r"), {**DEFAULTS, "model": "anthropic/claude-3-haiku"})
        cmd = mock_run.call_args[0][0]
        assert "anthropic/claude-3-haiku" in cmd
        assert "anthropic/anthropic/" not in " ".join(cmd)

    def test_passes_dir_flag(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_opencode_success())
        run_opencode("q", Path("/my/repo"), dict(DEFAULTS))
        cmd = mock_run.call_args[0][0]
        assert "--dir" in cmd
        idx = cmd.index("--dir")
        assert cmd[idx + 1] == "/my/repo"

    def test_passes_format_json(self, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=_make_opencode_success())
        run_opencode("q", Path("/r"), dict(DEFAULTS))
        cmd = mock_run.call_args[0][0]
        assert "--format" in cmd
        idx = cmd.index("--format")
        assert cmd[idx + 1] == "json"

    def test_file_not_found_raises_runtime_error(self, mocker):
        mocker.patch("subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(RuntimeError, match="opencode CLI not found"):
            run_opencode("q", Path("/r"), dict(DEFAULTS))

    def test_timeout_raises_runtime_error(self, mocker):
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="opencode", timeout=300),
        )
        with pytest.raises(RuntimeError, match="timed out"):
            run_opencode("q", Path("/r"), dict(DEFAULTS))

    def test_nonzero_exit_raises_runtime_error(self, mocker):
        mock = MagicMock()
        mock.returncode = 1
        mock.stderr = "server error"
        mock.stdout = ""
        mocker.patch("subprocess.run", return_value=mock)
        with pytest.raises(RuntimeError, match="status 1"):
            run_opencode("q", Path("/r"), dict(DEFAULTS))

    def test_nonzero_exit_includes_stderr(self, mocker):
        mock = MagicMock()
        mock.returncode = 1
        mock.stderr = "rate limited"
        mock.stdout = ""
        mocker.patch("subprocess.run", return_value=mock)
        with pytest.raises(RuntimeError, match="rate limited"):
            run_opencode("q", Path("/r"), dict(DEFAULTS))
