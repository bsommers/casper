"""TC-005: Strict downward-only module rank DAG enforcement via Python AST."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = ROOT / "src" / "casper"

MODULE_RANK: dict[str, int] = {
    "errors": 1,
    "models": 1,
    "documents": 1,
    "parsing": 1,
    "libraries": 1,
    "rewrites": 1,
    "loaders": 2,
    "features": 2,
    "profile": 2,
    "layers": 3,
    "conformance": 3,
    "facts": 3,
    "catalog": 4,
    "planner": 4,
    "modalities": 4,
    "realizer": 5,
    "llm": 5,
    "validator": 5,
    "pipeline": 6,
    "commands": 7,
    "web": 8,
    "cli": 8,
    "__init__": 8,
}

ALLOWED_SAME_RANK: set[tuple[str, str]] = {
    ("models", "errors"),
    ("documents", "models"),
    ("documents", "errors"),
    ("libraries", "models"),
    ("libraries", "errors"),
    ("rewrites", "models"),
    ("parsing", "errors"),
    ("profile", "loaders"),
    ("profile", "features"),
    ("conformance", "layers"),
    ("llm", "realizer"),
    ("cli", "web"),
}


def _top_module(py_file: Path) -> str:
    rel = py_file.relative_to(PKG_DIR)
    if rel.name == "__init__.py" and len(rel.parts) == 1:
        return "__init__"
    first = rel.parts[0]
    return first[:-3] if first.endswith(".py") else first


def _extract_casper_imports(py_file: Path, current_pkg: tuple[str, ...]) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "casper":
                    targets.append("__init__")
                elif alias.name.startswith("casper."):
                    targets.append(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base = current_pkg[: max(0, len(current_pkg) - (node.level - 1))]
                if node.module:
                    parts = (*base, *node.module.split("."))
                else:
                    parts = base
                if len(parts) >= 2 and parts[0] == "casper":
                    targets.append(parts[1])
                elif len(parts) == 1 and parts[0] == "casper":
                    for alias in node.names:
                        targets.append(alias.name)
            elif node.module:
                if node.module == "casper":
                    for alias in node.names:
                        targets.append(alias.name if alias.name in MODULE_RANK else "__init__")
                elif node.module.startswith("casper."):
                    targets.append(node.module.split(".")[1])
    return targets


def test_strict_module_rank_dag() -> None:
    violations: list[str] = []
    for py_file in sorted(PKG_DIR.rglob("*.py")):
        src_mod = _top_module(py_file)
        assert src_mod in MODULE_RANK, f"Unranked module in src/casper: {py_file.relative_to(ROOT)}"
        src_rank = MODULE_RANK[src_mod]

        rel = py_file.relative_to(ROOT / "src")
        if rel.name == "__init__.py":
            current_pkg = rel.parts[:-1]
        else:
            current_pkg = rel.parts[:-1]

        for dst_mod in _extract_casper_imports(py_file, current_pkg):
            if dst_mod not in MODULE_RANK:
                continue
            if dst_mod == src_mod:
                continue  # intra-package submodule import
            dst_rank = MODULE_RANK[dst_mod]

            if src_mod == "validator" and dst_mod in {"realizer", "llm"}:
                violations.append(f"FORBIDDEN: {src_mod} imports {dst_mod} ({py_file.name})")
            elif src_mod == "commands" and dst_mod in {"cli", "web"}:
                violations.append(f"FORBIDDEN: {src_mod} imports {dst_mod} ({py_file.name})")
            elif src_rank < dst_rank:
                violations.append(
                    f"UPWARD: {src_mod}(rank {src_rank}) -> {dst_mod}(rank {dst_rank}) in {py_file.relative_to(ROOT)}"
                )
            elif src_rank == dst_rank and (src_mod, dst_mod) not in ALLOWED_SAME_RANK:
                violations.append(
                    f"UNLISTED PEER: {src_mod}(rank {src_rank}) -> {dst_mod}(rank {dst_rank}) in {py_file.relative_to(ROOT)}"
                )
    assert not violations, "Architecture DAG violations:\n" + "\n".join(violations)
