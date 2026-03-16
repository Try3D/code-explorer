import logging
import logging.handlers
from pathlib import Path

from jsonc_parser.parser import JsoncParser

CACHE_DIR = Path.home() / ".code-explorer"
# Prefer config.jsonc, fall back to config.json
CONFIG_PATH = CACHE_DIR / "config.jsonc"
CONFIG_PATH_JSON = CACHE_DIR / "config.json"

DEFAULTS = {
    "cli": "claude",
    "model": "haiku",
    "allowed_tools": ["Bash", "Read", "Glob", "Grep"],
    "max_turns": 20,
    "repos_dir": str(CACHE_DIR / "repos"),
}


def load_config() -> dict:
    config = dict(DEFAULTS)
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_PATH_JSON
    if path.exists():
        overrides = JsoncParser.parse_file(str(path))
        config.update(overrides)
    return config


def get_repos_dir(config: dict) -> Path:
    return Path(config["repos_dir"]).expanduser()


def ensure_cache_dir(config: dict) -> None:
    get_repos_dir(config).mkdir(parents=True, exist_ok=True)


def setup_logging() -> logging.Logger:
    """Configure file logging to ~/.code-explorer/code-explorer.log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CACHE_DIR / "code-explorer.log"

    logger = logging.getLogger("code_explorer")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger
