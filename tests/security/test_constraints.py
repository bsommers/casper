"""TC-028: Enforce GC-01 (no Hugging Face or Python LLM SDKs) and GC-02 (pinned stack)."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PACKAGES = frozenset(
    {
        "transformers",
        "datasets",
        "huggingface-hub",
        "huggingface_hub",
        "torch",
        "openai",
        "anthropic",
        "google-genai",
        "google_genai",
        "google-generativeai",
        "google_generativeai",
        "litellm",
        "langchain",
        "llama-index",
        "llama_index",
    }
)

ALLOWED_RUNTIME_PACKAGES = frozenset(
    {
        "spacy",
        "en-core-web-sm",
        "scikit-learn",
        "networkx",
        "pyyaml",
        "beautifulsoup4",
        "lxml",
        "pypdf",
        "python-docx",
        "striprtf",
    }
)


def _normalize_dep_name(spec: str) -> str:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", spec)
    assert match, f"Unparseable dependency spec: {spec!r}"
    return match.group(1).lower().replace("_", "-")


def scan_python_source_for_forbidden_imports(source: str, filename: str = "<mem>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0].lower()
                if root_pkg in FORBIDDEN_PACKAGES or root_pkg.replace("_", "-") in FORBIDDEN_PACKAGES:
                    found.append(f"{filename}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_pkg = node.module.split(".")[0].lower()
            if root_pkg in FORBIDDEN_PACKAGES or root_pkg.replace("_", "-") in FORBIDDEN_PACKAGES:
                found.append(f"{filename}: from {node.module} import ...")
    return found


def test_pyproject_dependencies_strictly_compliant() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["requires-python"] == ">=3.11,<3.14"

    runtime_deps = [_normalize_dep_name(d) for d in project.get("dependencies", [])]
    for dep in runtime_deps:
        assert dep not in FORBIDDEN_PACKAGES, f"Forbidden dependency in pyproject.toml: {dep}"
        assert dep in ALLOWED_RUNTIME_PACKAGES, f"Unexpected runtime dependency (GC-02): {dep}"

    for group_deps in project.get("optional-dependencies", {}).values():
        for spec in group_deps:
            dep = _normalize_dep_name(spec)
            assert dep not in FORBIDDEN_PACKAGES, f"Forbidden optional dependency: {dep}"


def test_src_contains_no_forbidden_imports() -> None:
    violations: list[str] = []
    for py_file in sorted((ROOT / "src").rglob("*.py")):
        violations.extend(
            scan_python_source_for_forbidden_imports(
                py_file.read_text(encoding="utf-8"),
                str(py_file.relative_to(ROOT)),
            )
        )
    assert not violations, "Forbidden imports detected:\n" + "\n".join(violations)


def test_detector_catches_forbidden_import_negative_fixture() -> None:
    sample = "import openai\nfrom transformers import AutoModel\n"
    hits = scan_python_source_for_forbidden_imports(sample, "negative_fixture.py")
    assert len(hits) == 2
