"""Multi-language source file scanner for rescan_stale and codebrain new/rescan.

Supports Python (stdlib AST) and TypeScript/JavaScript/Swift/Kotlin (tree-sitter).
Tree-sitter packages are optional — falls back gracefully to [] for unsupported files.
"""
import ast
import fnmatch
import hashlib
import re
from collections import namedtuple
from pathlib import Path

_Profile = namedtuple("_Profile", ["name"])
_CodeUnit = namedtuple("_CodeUnit", [
    "name", "file_path", "source", "source_hash",
    "cyclomatic_complexity", "criticality_score", "assessment_profile",
])

# ---------------------------------------------------------------------------
# Tree-sitter multi-language support (optional — falls back gracefully)
# ---------------------------------------------------------------------------

_TS_PARSERS: dict = {}  # language_key → tree_sitter.Parser, cached


def _get_ts_parser(lang: str):
    """Return a cached tree-sitter Parser for lang, or None if unavailable."""
    if lang in _TS_PARSERS:
        return _TS_PARSERS[lang]
    try:
        from tree_sitter import Language, Parser
        if lang == "typescript":
            import tree_sitter_typescript as _m
            language = Language(_m.language_typescript())
        elif lang == "tsx":
            import tree_sitter_typescript as _m
            language = Language(_m.language_tsx())
        elif lang == "javascript":
            import tree_sitter_javascript as _m
            language = Language(_m.language())
        elif lang == "swift":
            import tree_sitter_swift as _m
            language = Language(_m.language())
        elif lang == "kotlin":
            import tree_sitter_kotlin as _m
            language = Language(_m.language())
        else:
            _TS_PARSERS[lang] = None
            return None
        parser = Parser(language)
        _TS_PARSERS[lang] = parser
        return parser
    except Exception:
        _TS_PARSERS[lang] = None
        return None


_TS_FUNCTION_NODES = {
    "typescript": ("function_declaration", "method_definition"),
    "tsx":        ("function_declaration", "method_definition"),
    "javascript": ("function_declaration", "method_definition"),
    "swift":      ("function_declaration", "init_declaration"),
    "kotlin":     ("function_declaration",),
}

_EXT_TO_LANG = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
}

_SKIP_DIRS: frozenset = frozenset({
    ".venv", "venv", "env", ".conda", ".conda-env",
    "node_modules",
    "__pycache__",
    ".git",
    "build", "dist",
    ".eggs", ".tox",
    ".next", ".nuxt",
})

_SUPPORTED_EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".swift", ".kt", ".kts"})


def _scan_treesitter(path: Path, lang: str) -> list[dict]:
    """Extract named functions/methods from a file using tree-sitter."""
    parser = _get_ts_parser(lang)
    if parser is None:
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = parser.parse(source.encode())
    except Exception:
        return []

    fn_node_types = _TS_FUNCTION_NODES.get(lang, ())
    results = []

    def _walk(node):
        if node.type in fn_node_types:
            name_node = next(
                (c for c in node.children if c.type in (
                    "identifier", "property_identifier", "simple_identifier"
                )),
                None,
            )
            if name_node:
                fn_name = name_node.text.decode(errors="replace")
                fn_source = source[node.start_byte:node.end_byte]
                results.append({
                    "fn_name": fn_name,
                    "file_path": str(path.resolve()),
                    "source": fn_source,
                    "lineno": node.start_point[0] + 1,
                })
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return results


def _scan_python(path: Path, include_private: bool = False) -> list[dict]:
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


def scan_file(path: str | Path, include_private: bool = False) -> list[dict]:
    """
    Return function info dicts for every function defined in the file.
    Each dict: {"fn_name", "file_path", "source", "lineno"}.
    Supports Python (AST), TypeScript, JavaScript, Swift, Kotlin (tree-sitter).
    Returns [] on parse error or unsupported extension.
    
    @feature: Ingestion
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".py", ".pyw"):
        return _scan_python(path, include_private)
    lang = _EXT_TO_LANG.get(ext)
    if lang:
        return _scan_treesitter(path, lang)
    return []


def scan_directory(
    root: str | Path,
    recursive: bool = True,
    include_private: bool = False,
    exclude_patterns: list | None = None,
) -> list[dict]:
    """Walk root and scan all supported source files.
    @feature: Ingestion
    """
    root = Path(root)
    exclude_patterns = exclude_patterns or []
    results = []
    glob_all = root.rglob("*") if recursive else root.glob("*")
    for src_file in sorted(f for f in glob_all if f.suffix.lower() in _SUPPORTED_EXTS):
        if any(part in _SKIP_DIRS for part in src_file.parts):
            continue
        if exclude_patterns:
            rel_str = str(src_file)
            if any(fnmatch.fnmatch(rel_str, p) for p in exclude_patterns):
                continue
        results.extend(scan_file(src_file, include_private=include_private))
    return results


def extract_concept_refs(path: str | Path) -> dict[str, list[str]]:
    """
    Scan a Python file for concept references in two forms:
      - Docstring tags:   @concept: JWT, Token Refresh
      - Inline comments:  [concept: bcrypt, timing-attack-prevention]

    Returns {concept_name: ["file:line", ...]} for every referenced concept.
    Returns {} for non-Python files or parse errors.
    
    @feature: Ingestion
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

    for lineno, line in enumerate(source.splitlines(), start=1):
        for m in re.finditer(r"\[concept:\s*([^\]]+)\]", line):
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            for name in names:
                refs.setdefault(name, []).append(f"{path_str}:{lineno}")

    return refs


def scan_concept_refs(root: str | Path) -> dict[str, list[str]]:
    """Walk all Python files under root and collect concept references.
    @feature: Ingestion
    """
    root = Path(root)
    merged: dict[str, list[str]] = {}
    for py_file in root.rglob("*.py"):
        for name, locs in extract_concept_refs(py_file).items():
            merged.setdefault(name, []).extend(locs)
    return merged


def batch_ingest(scan_results: list[dict]) -> list[tuple]:
    """Wrap scan results in namedtuples compatible with rescan_stale.
    @feature: Ingestion
    """
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
