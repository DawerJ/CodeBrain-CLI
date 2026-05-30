"""Minimal Python file scanner for rescan_stale — stdlib only, no external dependencies."""
import ast
import hashlib
from collections import namedtuple
from pathlib import Path

_Profile = namedtuple("_Profile", ["name"])
_CodeUnit = namedtuple("_CodeUnit", [
    "name", "file_path", "source", "source_hash",
    "cyclomatic_complexity", "criticality_score", "assessment_profile",
])


def scan_file(path: str | Path, include_private: bool = False) -> list[dict]:
    """
    Return function info dicts for every function in the file.
    Returns [] for non-Python files or files that fail to parse.
    """
    path = Path(path)
    if path.suffix not in (".py", ".pyw"):
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not include_private and node.name.startswith("_"):
            continue
        fn_source = ast.get_source_segment(source, node)
        if fn_source:
            results.append({
                "fn_name": node.name,
                "file_path": str(path.resolve()),
                "source": fn_source,
                "lineno": node.lineno,
            })
    return results


def batch_ingest(scan_results: list[dict]) -> list[tuple]:
    """Wrap scan results in namedtuples compatible with rescan_stale."""
    out = []
    for r in scan_results:
        src = r["source"]
        cu = _CodeUnit(
            name=r["fn_name"],
            file_path=r["file_path"],
            source=src,
            source_hash=hashlib.sha256(src.encode()).hexdigest()[:16],
            cyclomatic_complexity=None,
            criticality_score=None,
            assessment_profile=_Profile(name="LIGHT"),
        )
        out.append((cu, r))
    return out
