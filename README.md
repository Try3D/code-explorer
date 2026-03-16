# code-explorer MCP Server

An MCP server that answers questions about any repository's codebase.

## How It Works

1. You call `code_explorer_query` with a Git repository URL and a question
2. The server clones the repo into `~/.code-explorer/repos/<owner>/<repo>/` (or pulls latest if already cloned)
3. A `claude -p` subprocess runs with the repo as `cwd`, using `Bash`, `Read`, `Glob`, and `Grep` tools to explore the code
4. The answer is returned to you

## Requirements

- Python 3.10+
- `claude` CLI installed (`npm install -g @anthropic-ai/claude-code`) **or** `opencode` CLI
- Git

## Setup

```bash
# Create and activate virtual environment
uv venv --python 3.12 .venv
source .venv/bin/activate

# Install dependencies
uv pip install "mcp[cli]" gitpython
```

## Configuration

Create `~/.code-explorer/config.json` to customize behavior (all fields optional):

```json
{
  "cli": "claude",
  "model": "haiku",
  "allowed_tools": ["Bash", "Read", "Glob", "Grep"],
  "max_turns": 20,
  "repos_dir": "~/.code-explorer/repos"
}
```

| Field | Default | Options |
|-------|---------|---------|
| `cli` | `"claude"` | `"claude"` or `"opencode"` |
| `model` | `"haiku"` | Any model alias supported by your CLI |
| `allowed_tools` | `["Bash","Read","Glob","Grep"]` | Any Claude Code tool names |
| `max_turns` | `20` | Integer |
| `repos_dir` | `~/.code-explorer/repos` | Any path |

## Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "code-explorer": {
      "command": "/path/to/get-context/.venv/bin/python",
      "args": ["/path/to/get-context/server.py"]
    }
  }
}
```

## Claude Code Integration

```bash
claude mcp add code-explorer /path/to/get-context/.venv/bin/python -- /path/to/get-context/server.py
```

## Repo Cache

Repos are cached at `~/.code-explorer/repos/`. Subsequent queries to the same repo skip cloning and just `git pull`.
