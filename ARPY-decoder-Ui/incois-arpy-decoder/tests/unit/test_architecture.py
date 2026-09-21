"""Architecture guardrail tests (MIGRATION_DIRECT_PLAN §7.4).

Science/decoder modules MUST NOT import concrete metadata loaders
(``csv_loader``, future ``sqlite_loader`` / ``postgres_loader``). They
only import ``metadata.models`` types.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "argo_decoder"

FORBIDDEN_IMPORTS = {
    "argo_decoder.metadata.csv_loader",
    "argo_decoder.metadata.sqlite_loader",
    "argo_decoder.metadata.postgres_loader",
}

# Directories / modules allowed to import concrete loaders.
# Paths are stored with POSIX separators; _is_allowed() normalises both
# sides so the test works on Windows too.
ALLOWED = {
    "pipeline/metadata_stage.py",
    "pipeline/dual_run.py",
    "cli/main.py",
    "cli/metadata_cli.py",
    "cli/",  # future CLI submodules
    "metadata/csv_loader.py",
    "metadata/loader.py",
    "metadata/__init__.py",
}


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _forbidden_imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in FORBIDDEN_IMPORTS:
                found.append(mod)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORTS:
                    found.append(alias.name)
    return found


def _is_allowed(rel_posix: str) -> bool:
    """Return True if the POSIX-style relative path matches an ALLOWED entry.

    Matching rules:
    - exact file match (e.g. ``pipeline/metadata_stage.py``).
    - directory-prefix match (entries ending in ``/`` match anything under
      that directory, e.g. ``cli/`` matches ``cli/main.py``,
      ``cli/metadata_cli.py``, and ``cli/any_subdir/...``).
    """
    for a in ALLOWED:
        if a.endswith("/"):
            if rel_posix == a.rstrip("/") or rel_posix.startswith(a):
                return True
        else:
            if rel_posix == a:
                return True
    return False


@pytest.mark.parametrize(
    "path",
    sorted(_iter_python_files(SRC)),
    ids=lambda p: str(p.relative_to(SRC).as_posix()),
)
def test_no_concrete_metadata_loader_imports(path: Path):
    rel = path.relative_to(SRC).as_posix()  # normalise for cross-platform
    bad = _forbidden_imports_in(path)
    if bad and not _is_allowed(rel):
        pytest.fail(
            f"{rel} imports concrete metadata loader(s) {bad}; "
            "science/decoder modules must import metadata.models only."
        )
