#!/usr/bin/env python3
"""
code-explorer CLI

Usage:
  python cli.py <repo_url> "<query>" [--branch <branch>] [--cli claude|opencode] [--model <model>]

Examples:
  python cli.py https://github.com/anthropics/anthropic-sdk-python "What HTTP client does this SDK use?"
  python cli.py https://gitlab.com/inkscape/inkscape "How is the SVG parser structured?" --branch master
  python cli.py git@github.com:fastapi/fastapi.git "What is the dependency injection system?" --cli claude --model sonnet
"""

import argparse
import sys

import cli_runner
import config as cfg_module
import repo_manager


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="code-explorer",
        description="Ask questions about any Git repository's codebase.",
    )
    parser.add_argument("repo_url", help="Git repository URL")
    parser.add_argument("query", help="Question about the codebase")
    parser.add_argument("--branch", default=None, help="Git branch to analyze")
    parser.add_argument(
        "--cli",
        choices=["claude", "opencode"],
        default=None,
        help="CLI backend to use (overrides config)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use (overrides config, e.g. anthropic/claude-haiku-4.5, sonnet)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        dest="max_turns",
        help="Maximum agent turns (overrides config)",
    )

    args = parser.parse_args()

    config = cfg_module.load_config()
    if args.cli:
        config["cli"] = args.cli
    if args.model:
        config["model"] = args.model
    if args.max_turns:
        config["max_turns"] = args.max_turns

    print(f"[cex] repo:   {args.repo_url}")
    print(f"[cex] query:  {args.query}")
    print(f"[cex] cli:    {config['cli']}  model: {config['model']}")
    if args.branch:
        print(f"[cex] branch: {args.branch}")
    print()

    cfg_module.ensure_cache_dir(config)
    try:
        owner, repo, local_path, clone_url = repo_manager.parse_git_url(args.repo_url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[cex] ensuring repo {owner}/{repo} ...")
    try:
        resolved_branch = repo_manager.ensure_repo(
            owner, repo, local_path, clone_url, args.branch
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[cex] branch: {resolved_branch}")
    print(f"[cex] local:  {local_path}")
    print(f"[cex] running agent ...\n")

    try:
        answer = cli_runner.run_query(args.query, local_path, config)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(answer)


if __name__ == "__main__":
    main()
