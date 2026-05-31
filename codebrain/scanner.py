"""Minimal Python file scanner for rescan_stale — stdlib only, no external dependencies."""
import ast
import hashlib
import re
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


def extract_concept_refs(path: str | Path) -> dict[str, list[str]]:
    """
    Scan a Python file for concept references in two forms:
      - Docstring tags:   @concept: JWT, Token Refresh
      - Inline comments:  [concept: bcrypt, timing-attack-prevention]

    Returns {concept_name: ["file:line", ...]} for every referenced concept.
    Returns {} for non-Python files or parse errors.
    """
    path = Path(path)
    if path.suffix not in (".py", ".pyw"):
        return {}
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    refs: dict[str, list[str]] = {}
    path_str = str(path.resolve())

    # @concept: tag in docstrings — extract via AST for accurate line numbers
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                continue
            docstring = ast.get_docstring(node)
            if not docstring:
                continue
            for m in re.finditer(r"@concept:\s*(.+)", docstring):
                names = [n.strip() for n in m.group(1).split(",") if n.strip()]
                lineno = node.lineno if hasattr(node, "lineno") else 0
                for name in names:
                    refs.setdefault(name, []).append(f"{path_str}:{lineno}")
    except Exception:
        pass

    # [concept: X] inline comment form — line-by-line regex
    for lineno, line in enumerate(source.splitlines(), start=1):
        for m in re.finditer(r"\[concept:\s*([^\]]+)\]", line):
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            for name in names:
                refs.setdefault(name, []).append(f"{path_str}:{lineno}")

    return refs


def scan_concept_refs(root: str | Path) -> dict[str, list[str]]:
    """
    Walk all Python files under root and collect concept references.
    Returns merged {concept_name: ["file:line", ...]} dict.
    """
    root = Path(root)
    merged: dict[str, list[str]] = {}
    for py_file in root.rglob("*.py"):
        for name, locs in extract_concept_refs(py_file).items():
            merged.setdefault(name, []).extend(locs)
    return merged


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
