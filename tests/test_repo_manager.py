"""Tests for code_explorer.repo_manager.

Focus on two areas:
1. parse_git_url — pure URL parsing logic, many edge cases
2. ensure_repo — git clone/fetch/checkout lifecycle (uses real git repos in tmp_path)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import git
import pytest

from code_explorer.repo_manager import (
    _get_current_branch,
    ensure_repo,
    parse_git_url,
)


@pytest.fixture(autouse=True)
def patch_load_config(monkeypatch, tmp_path):
    """Redirect load_config so parse_git_url uses tmp_path as repos_dir."""
    monkeypatch.setattr(
        "code_explorer.repo_manager.load_config",
        lambda: {"repos_dir": str(tmp_path)},
    )
    return tmp_path


# ===========================================================================
# parse_git_url — HTTPS
# ===========================================================================


class TestParseHttpsUrls:
    def test_basic_github(self, tmp_path):
        owner, repo, local_path, clone_url = parse_git_url(
            "https://github.com/anthropics/anthropic-sdk-python"
        )
        assert owner == "anthropics"
        assert repo == "anthropic-sdk-python"
        assert clone_url == "https://github.com/anthropics/anthropic-sdk-python.git"

    def test_with_git_suffix(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("https://github.com/fastapi/fastapi.git")
        assert owner == "fastapi"
        assert repo == "fastapi"
        assert clone_url.endswith(".git")
        # Should not double up .git
        assert not clone_url.endswith(".git.git")

    def test_with_tree_path_stripped(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url(
            "https://github.com/owner/myrepo/tree/main/src/subdir"
        )
        assert owner == "owner"
        assert repo == "myrepo"
        assert clone_url == "https://github.com/owner/myrepo.git"

    def test_with_blob_path_stripped(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url(
            "https://github.com/owner/myrepo/blob/main/README.md"
        )
        assert owner == "owner"
        assert repo == "myrepo"

    def test_with_pulls_path_stripped(self, tmp_path):
        owner, repo, _, _ = parse_git_url(
            "https://github.com/owner/myrepo/pulls"
        )
        assert owner == "owner"
        assert repo == "myrepo"

    def test_gitlab_url(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("https://gitlab.com/inkscape/inkscape")
        assert owner == "inkscape"
        assert repo == "inkscape"
        assert clone_url == "https://gitlab.com/inkscape/inkscape.git"

    def test_bitbucket_url(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("https://bitbucket.org/atlassian/stash")
        assert owner == "atlassian"
        assert repo == "stash"

    def test_http_without_s(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("http://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert clone_url.startswith("http://")

    def test_clone_url_preserves_https_protocol(self, tmp_path):
        _, _, _, clone_url = parse_git_url("https://github.com/owner/repo")
        assert clone_url.startswith("https://")

    def test_clone_url_preserves_http_protocol(self, tmp_path):
        _, _, _, clone_url = parse_git_url("http://github.com/owner/repo")
        assert clone_url.startswith("http://")

    def test_custom_host(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("https://git.mycompany.com/team/project")
        assert owner == "team"
        assert repo == "project"
        assert "git.mycompany.com" in clone_url


# ===========================================================================
# parse_git_url — SSH
# ===========================================================================


class TestParseSshUrls:
    def test_basic_github(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("git@github.com:fastapi/fastapi.git")
        assert owner == "fastapi"
        assert repo == "fastapi"
        assert clone_url == "git@github.com:fastapi/fastapi.git"

    def test_without_git_suffix(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("git@github.com:owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert clone_url == "git@github.com:owner/repo.git"

    def test_different_host(self, tmp_path):
        _, _, _, clone_url = parse_git_url("git@bitbucket.org:atlassian/localstack.git")
        assert clone_url == "git@bitbucket.org:atlassian/localstack.git"

    def test_gitlab_ssh(self, tmp_path):
        owner, repo, _, clone_url = parse_git_url("git@gitlab.com:group/project.git")
        assert owner == "group"
        assert repo == "project"
        assert "gitlab.com" in clone_url

    def test_clone_url_always_has_git_suffix(self, tmp_path):
        _, _, _, clone_url = parse_git_url("git@github.com:a/b")
        assert clone_url.endswith(".git")

    def test_repo_with_dots_in_name(self, tmp_path):
        owner, repo, _, _ = parse_git_url("git@github.com:owner/my.repo.name")
        assert owner == "owner"
        assert repo == "my.repo.name"

    def test_repo_with_hyphens_and_underscores(self, tmp_path):
        owner, repo, _, _ = parse_git_url("git@github.com:my-org/my_repo-name")
        assert owner == "my-org"
        assert repo == "my_repo-name"


# ===========================================================================
# parse_git_url — whitespace handling
# ===========================================================================


class TestParseWhitespace:
    def test_leading_whitespace_stripped(self, tmp_path):
        owner, _, _, _ = parse_git_url("  https://github.com/owner/repo")
        assert owner == "owner"

    def test_trailing_whitespace_stripped(self, tmp_path):
        owner, _, _, _ = parse_git_url("https://github.com/owner/repo  ")
        assert owner == "owner"

    def test_leading_and_trailing_whitespace(self, tmp_path):
        owner, _, _, _ = parse_git_url("  https://github.com/owner/repo  \n")
        assert owner == "owner"


# ===========================================================================
# parse_git_url — invalid inputs
# ===========================================================================


class TestParseInvalidUrls:
    def test_not_a_url(self):
        with pytest.raises(ValueError):
            parse_git_url("not-a-url")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_git_url("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError):
            parse_git_url("   ")

    def test_path_traversal_in_owner(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_git_url("https://github.com/../etc/passwd")

    def test_path_traversal_in_repo(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_git_url("https://github.com/owner/repo..name")

    def test_backslash_in_owner(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_git_url("https://github.com/ow\\ner/repo")

    def test_backslash_in_repo_ssh(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_git_url("git@github.com:owner/re\\po")

    def test_ftp_protocol_rejected(self):
        with pytest.raises(ValueError):
            parse_git_url("ftp://github.com/owner/repo")

    def test_bare_domain_no_path(self):
        with pytest.raises(ValueError):
            parse_git_url("https://github.com")

    def test_single_path_component(self):
        with pytest.raises(ValueError):
            parse_git_url("https://github.com/onlyone")


# ===========================================================================
# parse_git_url — return value structure
# ===========================================================================


class TestParseReturnStructure:
    def test_returns_four_tuple(self, tmp_path):
        result = parse_git_url("https://github.com/owner/repo")
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_local_path_is_path_type(self, tmp_path):
        _, _, local_path, _ = parse_git_url("https://github.com/owner/repo")
        assert isinstance(local_path, Path)

    def test_local_path_structure(self, tmp_path):
        _, _, local_path, _ = parse_git_url("https://github.com/owner/myrepo")
        assert local_path == tmp_path / "owner" / "myrepo"

    def test_clone_url_is_string(self, tmp_path):
        _, _, _, clone_url = parse_git_url("https://github.com/owner/repo")
        assert isinstance(clone_url, str)

    def test_owner_and_repo_are_strings(self, tmp_path):
        owner, repo, _, _ = parse_git_url("https://github.com/owner/repo")
        assert isinstance(owner, str)
        assert isinstance(repo, str)


# ===========================================================================
# ensure_repo — with real git repos
# ===========================================================================


@pytest.fixture
def bare_repo(tmp_path):
    """Create a bare git repo to serve as the 'remote'."""
    bare_path = tmp_path / "bare_remote.git"
    bare = git.Repo.init(str(bare_path), bare=True)
    bare.close()

    # Need at least one commit so clone works
    work = tmp_path / "work_setup"
    work.mkdir()
    r = git.Repo.init(str(work))
    r.config_writer().set_value("user", "name", "Test").release()
    r.config_writer().set_value("user", "email", "test@test.com").release()
    (work / "README.md").write_text("hello")
    r.index.add(["README.md"])
    r.index.commit("initial commit")
    r.create_remote("origin", str(bare_path))
    r.remotes.origin.push("HEAD:refs/heads/main")

    # Create a second branch on the remote
    r.git.checkout("-b", "feature-branch")
    (work / "feature.txt").write_text("feature work")
    r.index.add(["feature.txt"])
    r.index.commit("feature commit")
    r.remotes.origin.push("HEAD:refs/heads/feature-branch")

    r.close()
    return bare_path


class TestEnsureRepo:
    def test_clones_fresh_repo(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        branch = ensure_repo("owner", "repo", local, str(bare_repo), branch="main")
        assert (local / ".git").is_dir()
        assert (local / "README.md").exists()
        assert branch == "main"

    def test_clones_default_branch_when_none(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        branch = ensure_repo("owner", "repo", local, str(bare_repo), branch=None)
        assert (local / ".git").is_dir()
        assert isinstance(branch, str)
        assert len(branch) > 0

    def test_clones_specific_branch(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        branch = ensure_repo("owner", "repo", local, str(bare_repo), branch="feature-branch")
        assert (local / "feature.txt").exists()
        assert branch == "feature-branch"

    def test_fetch_updates_existing_repo(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        # First clone
        ensure_repo("owner", "repo", local, str(bare_repo), branch="main")

        # Push a new commit to bare remote
        work = tmp_path / "work_update"
        r = git.Repo.clone_from(str(bare_repo), str(work), branch="main")
        r.config_writer().set_value("user", "name", "Test").release()
        r.config_writer().set_value("user", "email", "test@test.com").release()
        (work / "new_file.txt").write_text("new content")
        r.index.add(["new_file.txt"])
        r.index.commit("new commit")
        r.remotes.origin.push()
        r.close()

        # Second call should fetch + pull
        branch = ensure_repo("owner", "repo", local, str(bare_repo))
        assert (local / "new_file.txt").exists()
        assert branch == "main"

    def test_checkout_branch_on_existing_repo(self, tmp_path, bare_repo):
        """Switching branches on an existing shallow clone requires the ref to be fetchable."""
        local = tmp_path / "cloned" / "repo"
        # Clone without specifying branch — default fetch refspec covers all remote heads
        ensure_repo("owner", "repo", local, str(bare_repo), branch=None)

        # Widen the fetch refspec so feature-branch is available after fetch
        repo_obj = git.Repo(str(local))
        repo_obj.remotes.origin.config_writer.set("fetch", "+refs/heads/*:refs/remotes/origin/*")

        # Now checkout feature-branch
        branch = ensure_repo("owner", "repo", local, str(bare_repo), branch="feature-branch")
        assert branch == "feature-branch"
        assert (local / "feature.txt").exists()

    def test_clone_invalid_url_raises_runtime_error(self, tmp_path):
        local = tmp_path / "cloned" / "repo"
        with pytest.raises(RuntimeError, match="not found or inaccessible"):
            ensure_repo("owner", "repo", local, "file:///nonexistent/path.git")

    def test_returns_string_branch_name(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        result = ensure_repo("owner", "repo", local, str(bare_repo), branch="main")
        assert isinstance(result, str)

    def test_checkout_nonexistent_branch_raises(self, tmp_path, bare_repo):
        local = tmp_path / "cloned" / "repo"
        ensure_repo("owner", "repo", local, str(bare_repo), branch="main")
        with pytest.raises(RuntimeError, match="Could not checkout"):
            ensure_repo("owner", "repo", local, str(bare_repo), branch="no-such-branch")


# ===========================================================================
# _get_current_branch
# ===========================================================================


class TestGetCurrentBranch:
    def test_returns_branch_name(self, tmp_path):
        r = git.Repo.init(str(tmp_path / "repo"))
        r.config_writer().set_value("user", "name", "Test").release()
        r.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "repo" / "f.txt").write_text("x")
        r.index.add(["f.txt"])
        r.index.commit("init")
        assert _get_current_branch(r) == "master" or _get_current_branch(r) == "main"

    def test_returns_short_sha_on_detached_head(self, tmp_path):
        r = git.Repo.init(str(tmp_path / "repo"))
        r.config_writer().set_value("user", "name", "Test").release()
        r.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "repo" / "f.txt").write_text("x")
        r.index.add(["f.txt"])
        commit = r.index.commit("init")
        r.git.checkout(commit.hexsha)  # Detach HEAD
        result = _get_current_branch(r)
        assert len(result) == 8
        assert commit.hexsha.startswith(result)
