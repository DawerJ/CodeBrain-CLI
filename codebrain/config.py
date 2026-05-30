"""
.codebrain config — stores url, api_key, and codebase_id for each project.

Supports two layouts (migration from old→new happens automatically in `cmd_up`):

  Old (file):       .codebrain          ← JSON directly
  New (directory):  .codebrain/
                      config.json       ← credentials + metadata
                      session.md        ← written by get_session_context

The new layout lets session.md exist alongside the config without conflicts.
`migrate()` converts the old layout to the new one non-destructively.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = ".codebrain"
_CONFIG_JSON = "config.json"


def _config_path(root: Path) -> Path:
    """Return the config file path, preferring the new directory layout."""
    d = root / CONFIG_FILE
    if d.is_dir():
        return d / _CONFIG_JSON
    return d  # old layout: .codebrain is the file itself


def load(root: Path | None = None) -> dict:
    p = _config_path(root or Path("."))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(cfg: dict, root: Path | None = None) -> None:
    p = _config_path(root or Path("."))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def require(root: Path | None = None) -> dict:
    """Load config and raise if url/api_key are missing."""
    cfg = load(root)
    if not cfg.get("url") or not cfg.get("api_key"):
        raise RuntimeError(
            "No .codebrain config found or missing url/api_key.\n"
            "Run: codebrain init --url <url> --api-key <key> --path <src>"
        )
    return cfg


def migrate(root: Path | None = None) -> bool:
    """Convert .codebrain file → .codebrain/ directory if needed.

    Returns True if migration happened, False if already up to date or not applicable.
    Safe to call repeatedly — no-ops when .codebrain is already a directory.
    """
    r = root or Path(".")
    old = r / CONFIG_FILE
    if not old.exists() or old.is_dir():
        return False  # nothing to migrate

    # .codebrain is a file — read it, convert to directory layout
    try:
        content = old.read_text(encoding="utf-8")
        json.loads(content)  # validate it's JSON before touching anything
    except Exception:
        return False  # not valid JSON, leave it alone

    # Delete old file, create directory, write config.json inside.
    # Not atomic but safe: content is validated JSON before we touch anything.
    old.unlink()
    new_dir = r / CONFIG_FILE
    new_dir.mkdir()
    (new_dir / _CONFIG_JSON).write_text(content, encoding="utf-8")
    return True
