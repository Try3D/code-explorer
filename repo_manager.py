import re
from pathlib import Path

import git

from config import get_repos_dir, load_config


def parse_git_url(url: str) -> tuple[str, str, Path, str]:
    """
    Parse a Git URL and return (owner, repo, local_path, clone_url).

    Supported formats:
    - https://host/owner/repo
    - https://host/owner/repo.git
    - https://host/owner/repo/tree/branch/...
    - git@host:owner/repo.git
    """
    url = url.strip()

    # SSH: git@host:owner/repo.git
    ssh_match = re.match(r"^git@([^:]+):([^/]+)/(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, owner, repo = ssh_match.group(1), ssh_match.group(2), ssh_match.group(3)
        clone_url = f"git@{host}:{owner}/{repo}.git"
        owner_val, repo_val, local_path = _build_result(owner, repo)
        return owner_val, repo_val, local_path, clone_url

    # HTTPS: https://host/owner/repo[.git][/...]
    https_match = re.match(
        r"^(https?://[^/]+/([^/]+)/([^/]+?))(?:\.git)?(?:/.*)?$", url
    )
    if https_match:
        base, owner, repo = https_match.group(1), https_match.group(2), https_match.group(3)
        clone_url = f"{base}.git"
        owner_val, repo_val, local_path = _build_result(owner, repo)
        return owner_val, repo_val, local_path, clone_url

    raise ValueError(
        f"Invalid Git URL: {url!r}. "
        "Expected https://host/owner/repo or git@host:owner/repo.git"
    )


def _build_result(owner: str, repo: str) -> tuple[str, str, Path]:
    for part, name in ((owner, "owner"), (repo, "repo")):
        if ".." in part or "/" in part or "\\" in part:
            raise ValueError(f"Invalid {name} in Git URL: {part!r}")
    cfg = load_config()
    local_path = get_repos_dir(cfg) / owner / repo
    return owner, repo, local_path


def ensure_repo(owner: str, repo: str, local_path: Path, clone_url: str, branch: str | None = None) -> str:
    """
    Clone the repo if not present, or fetch + pull if it is.
    Returns the resolved branch name.
    """
    git_dir = local_path / ".git"

    if not git_dir.exists():
        local_path.mkdir(parents=True, exist_ok=True)
        clone_kwargs: dict = {"depth": 1}
        if branch:
            clone_kwargs["branch"] = branch
        try:
            repo_obj = git.Repo.clone_from(clone_url, str(local_path), **clone_kwargs)
        except git.GitCommandError as e:
            raise RuntimeError(
                f"Repository not found or inaccessible: {clone_url}\n{e}"
            ) from e
    else:
        repo_obj = git.Repo(str(local_path))
        try:
            repo_obj.remotes.origin.fetch()
        except git.GitCommandError as e:
            raise RuntimeError(f"Failed to fetch updates: {e}") from e

        if branch:
            _checkout_branch(repo_obj, branch)
        else:
            _pull_ff(repo_obj)

    active_branch = _get_current_branch(repo_obj)
    return active_branch


def _checkout_branch(repo_obj: git.Repo, branch: str) -> None:
    try:
        repo_obj.git.checkout(branch)
    except git.GitCommandError:
        # Branch not local yet — create tracking branch
        try:
            repo_obj.git.checkout("-b", branch, f"origin/{branch}")
        except git.GitCommandError as e:
            raise RuntimeError(f"Could not checkout branch {branch!r}: {e}") from e
    _pull_ff(repo_obj)


def _pull_ff(repo_obj: git.Repo) -> None:
    try:
        repo_obj.git.pull("--ff-only")
    except git.GitCommandError:
        # Non-fast-forward: re-clone to recover cleanly
        local_path = Path(repo_obj.working_dir)
        repo_obj.close()
        import shutil
        shutil.rmtree(str(local_path))
        raise RuntimeError(
            f"Pull failed (non-fast-forward). Removed local cache at {local_path}. "
            "Retry to re-clone from scratch."
        )


def _get_current_branch(repo_obj: git.Repo) -> str:
    try:
        return repo_obj.active_branch.name
    except TypeError:
        # Detached HEAD
        return repo_obj.head.commit.hexsha[:8]
