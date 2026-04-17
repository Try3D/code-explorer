import json
import subprocess
from pathlib import Path

from .config import setup_logging

log = setup_logging().getChild("runner")


def run_claude(query: str, cwd: Path, config: dict, session_id: str | None = None) -> tuple[str, str]:
    """Spawn `claude -p <query>` in the repo directory and return (answer, session_id)."""
    log.info("spawning claude (model=%s, max_turns=%s, resume=%s) in %s",
             config["model"], config["max_turns"], bool(session_id), cwd)
    cmd = ["claude"]
    if session_id:
        cmd += ["-r", session_id]
    cmd += [
        "-p", _wrap_query(query, cwd),
        "--model", config["model"],
        "--allowedTools", ",".join(config["allowed_tools"]),
        "--max-turns", str(config["max_turns"]),
        "--output-format", "json",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude CLI not found in PATH. "
            "Install it with: npm install -g @anthropic-ai/claude-code"
        )
    except subprocess.TimeoutExpired:
        log.error("claude timed out after 300s in %s", cwd)
        raise RuntimeError("claude agent timed out after 300 seconds")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        log.error("claude exited %s: %s", result.returncode, stderr)
        raise RuntimeError(
            f"claude exited with status {result.returncode}"
            + (f": {stderr}" if stderr else "")
        )

    log.info("claude completed successfully")
    return _extract_claude_answer(result.stdout)


def _extract_claude_answer(output: str) -> tuple[str, str]:
    """Parse claude's JSON output and return (answer_text, session_id).

    claude --output-format json emits a single JSON object like:
      {"type": "result", "subtype": "success", "result": "...", "session_id": "...", ...}
    """
    try:
        data = json.loads(output.strip())
        answer = data.get("result", "").strip()
        sid = data.get("session_id", "")
        return answer, sid
    except (json.JSONDecodeError, AttributeError):
        # Fallback: return raw output with empty session_id
        return output.strip(), ""


def _wrap_query(query: str, cwd: Path) -> str:
    """Prefix the query with context so the agent focuses on the local repo."""
    return (
        f"You are analyzing a local Git repository at: {cwd}\n"
        f"Answer the following question by exploring the files in that directory. "
        f"Do NOT search the web or reference external documentation. "
        f"Use only the code and files present in the repository.\n\n"
        f"Question: {query}"
    )


def run_opencode(query: str, cwd: Path, config: dict) -> str:
    """Spawn `opencode run <query>` in the repo directory and return the answer."""
    model = config["model"]
    # opencode uses provider/model format; if already qualified leave it, else prefix anthropic/
    if "/" not in model:
        model = f"anthropic/{model}"
    log.info("spawning opencode (model=%s) in %s", model, cwd)

    cmd = [
        "opencode", "run", _wrap_query(query, cwd),
        "--model", model,
        "--format", "json",
        "--dir", str(cwd),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "opencode CLI not found in PATH. "
            "Install it from: https://opencode.ai"
        )
    except subprocess.TimeoutExpired:
        log.error("opencode timed out after 300s in %s", cwd)
        raise RuntimeError("opencode agent timed out after 300 seconds")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        log.error("opencode exited %s: %s", result.returncode, stderr)
        raise RuntimeError(
            f"opencode exited with status {result.returncode}"
            + (f": {stderr}" if stderr else "")
        )

    log.info("opencode completed successfully")
    answer = _extract_opencode_answer(result.stdout)
    return answer


def _extract_opencode_answer(output: str) -> str:
    """Parse newline-delimited JSON from opencode and extract the final answer text.

    opencode --format json emits events like:
      {"type":"text", "part": {"type":"text", "text":"..."}}
      {"type":"tool_use", ...}
      {"type":"step_finish", "part": {"reason":"stop", ...}}

    We collect all top-level text events and return the last "stop"-terminated
    block, which is the final assistant answer.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]

    # Accumulate text segments; reset on each new step_start
    current_segment: list[str] = []
    final_segment: list[str] = []

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "step_start":
            current_segment = []
        elif etype == "text":
            text = event.get("part", {}).get("text", "")
            if text:
                current_segment.append(text)
        elif etype == "step_finish":
            reason = event.get("part", {}).get("reason", "")
            if reason == "stop" and current_segment:
                final_segment = list(current_segment)

    if final_segment:
        return "".join(final_segment).strip()

    # Fallback: join all text parts collected
    if current_segment:
        return "".join(current_segment).strip()

    return output.strip()


def run_query(query: str, cwd: Path, config: dict, session_id: str | None = None) -> tuple[str, str | None]:
    """Dispatch to the configured CLI backend. Returns (answer, session_id_or_None)."""
    cli = config.get("cli", "claude")
    if cli == "opencode":
        return run_opencode(query, cwd, config), None
    elif cli == "claude":
        return run_claude(query, cwd, config, session_id=session_id)
    else:
        raise ValueError(
            f"Unknown CLI backend {cli!r} in config. Must be 'claude' or 'opencode'."
        )
