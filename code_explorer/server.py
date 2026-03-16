from mcp.server.fastmcp import FastMCP

from . import cli_runner
from . import config as cfg_module
from . import repo_manager

mcp = FastMCP("code_explorer_mcp")
log = cfg_module.setup_logging().getChild("server")


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
        answer = cli_runner.run_query(query, local_path, config)
    except (ValueError, RuntimeError) as e:
        log.error("tool error: %s", e)
        return {"error": str(e)}

    return {
        "answer": answer,
        "repo": f"{owner}/{repo}",
        "branch": resolved_branch,
        "cli_used": config["cli"],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
