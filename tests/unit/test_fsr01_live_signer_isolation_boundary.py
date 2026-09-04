"""FSR-01 (``argus-final-spec-recovery-001``): production-capable
signer/submission isolation boundary.

Mirrors ``test_phase6_p6_02_signer_isolation_boundary.py``'s own
AST-based import-graph mechanism exactly, extended to the two new
live-capable modules this recovery item adds:
``argus.executor.live_signing`` (the only module that may load a real
Solana keypair) and ``argus.executor.live_submission`` (the only module
that may broadcast a signed transaction). Neither research/ingestion/
scoring/etc. package, nor ``argus/cli.py``, nor ``argus/api/`` may ever
import either module -- proven structurally, not by convention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "argus"
_NON_EXECUTOR_PACKAGES = (
    "copyability",
    "scoring",
    "ingestion",
    "wallets",
    "tokens",
    "shadow",
    "reports",
    "research",
    "signals",
    "outcomes",
    "notifications",
    "telegram",
    "clustering",
    "graph",
    "risk",
    "parsing",
    "providers",
    "api",
    "db",
    "domain",
    "convergence",
    "counterfactual",
    "synthetic",
    "prediction",
)

_LIVE_CAPABLE_MODULES = ("argus.executor.live_signing", "argus.executor.live_submission")


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("package_name", _NON_EXECUTOR_PACKAGES)
def test_non_executor_package_has_no_live_signer_or_submission_dependency(
    package_name: str,
) -> None:
    package_dir = _SRC / package_name
    if not package_dir.is_dir():
        pytest.skip(f"{package_name} package does not exist in this build")
    offenders = []
    for py_file in package_dir.rglob("*.py"):
        imported = _imported_module_names(py_file)
        if any(live_module in imported for live_module in _LIVE_CAPABLE_MODULES):
            offenders.append(str(py_file.relative_to(_REPO_ROOT)))
    assert offenders == [], f"unauthorized live signer/submission dependency in: {offenders}"


def test_cli_module_never_imports_live_signer_or_submission() -> None:
    imported = _imported_module_names(_SRC / "cli.py")
    for forbidden in _LIVE_CAPABLE_MODULES:
        assert forbidden not in imported


@pytest.mark.parametrize(
    "executor_module_filename",
    [
        p.name
        for p in sorted((_SRC / "executor").glob("*.py"))
        if p.name not in {"live_signing.py", "live_submission.py", "main.py", "__init__.py"}
    ],
)
def test_only_main_imports_the_live_capable_modules(executor_module_filename: str) -> None:
    """Even WITHIN ``argus.executor``, only the process entry point
    (``main.py``) may import the live-capable modules -- the readiness/
    persistence/state-machine/dispatch-sentinel modules that every
    report/CLI path already relies on must stay exactly as isolated from
    real key material as they were before FSR-01."""
    path = _SRC / "executor" / executor_module_filename
    imported = _imported_module_names(path)
    for forbidden in _LIVE_CAPABLE_MODULES:
        assert forbidden not in imported, f"{executor_module_filename} imports {forbidden}"


def test_main_module_is_the_one_place_that_imports_both_live_capable_modules() -> None:
    imported = _imported_module_names(_SRC / "executor" / "main.py")
    assert "argus.executor.live_signing" in imported
    assert "argus.executor.live_submission" in imported
