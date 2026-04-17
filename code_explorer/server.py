from mcp.server.fastmcp import FastMCP

from . import cli_runner
from . import config as cfg_module
from . import repo_manager
from .session_store import SessionStore

mcp = FastMCP("code_explorer_mcp")
log = cfg_module.setup_logging().getChild("server")
_session_store = SessionStore()


@mcp.tool()
def code_explorer_query(repo_url: str, query: str, branch: str | None = None) -> dict:
    """
    Explore a Git repository and answer questions about its codebase.

    Clones the repository locally into ~/.code-explorer/repos/<owner>/<repo>/ (or
    updates an existing clone), then spawns a claude or opencode CLI agent with
    the repo as its working directory to answer your question.

    The CLI backend and model are configured via ~/.code-explorer/config.json.
    If the file doesn't exist, defaults to claude with haiku model.

    Args:
        repo_url: Git repository URL. Supported formats:
                  https://host/owner/repo
                  https://host/owner/repo.git
                  git@host:owner/repo.git
        query: Your question about the codebase (10–2000 characters).
        branch: Git branch to analyze. Defaults to the repository's default branch.

    Returns:
        answer: The agent's answer to your question.
        repo: "owner/repo" identifier.
        branch: The branch that was analyzed.
        cli_used: Which CLI backend was used ("claude" or "opencode").
    """
    log.info("tool called: repo=%s branch=%s query=%r", repo_url, branch, query)
    config = cfg_module.load_config()
    cfg_module.ensure_cache_dir(config)

    try:
        owner, repo, local_path, clone_url = repo_manager.parse_git_url(repo_url)
        resolved_branch = repo_manager.ensure_repo(owner, repo, local_path, clone_url, branch)
    except (ValueError, RuntimeError) as e:
        log.error("tool error: %s", e)
        return {"error": str(e)}

    session_key = f"{owner}/{repo}@{resolved_branch}"
    existing_session = _session_store.get(session_key)
    log.info("session key=%s resume=%s", session_key, bool(existing_session))

    try:
        answer, new_session_id = cli_runner.run_query(query, local_path, config, session_id=existing_session)
    except RuntimeError as e:
        if existing_session:
            # Session may be stale — clear it and retry fresh
            log.warning("session %s failed (%s), retrying fresh", existing_session, e)
            _session_store.clear(session_key)
            try:
                answer, new_session_id = cli_runner.run_query(query, local_path, config)
            except RuntimeError as e2:
                log.error("tool error (fresh retry): %s", e2)
                return {"error": str(e2)}
        else:
            log.error("tool error: %s", e)
            return {"error": str(e)}

    if new_session_id:
        _session_store.save(session_key, new_session_id)

    return {
        "answer": answer,
        "repo": f"{owner}/{repo}",
        "branch": resolved_branch,
        "cli_used": config["cli"],
        "session_id": new_session_id or None,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
