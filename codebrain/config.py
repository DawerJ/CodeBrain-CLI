"""
.codebrain config file — stores url, api_key, and codebase_id for each project.

Format (JSON, lives at project root):
    {
        "url": "https://yourapp.railway.app",
        "api_key": "cb_...",
        "codebase_id": "05f81a84",
        "path": "./src"
    }

This file contains credentials — it is added to .gitignore automatically.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = ".codebrain"


def load(root: Path | None = None) -> dict:
    p = (root or Path(".")) / CONFIG_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(cfg: dict, root: Path | None = None) -> None:
    p = (root or Path(".")) / CONFIG_FILE
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
