"""P6-02 (SPEC_BLOCKING): executor key isolation boundary -- MASTER_SPEC.md
sections 70/71, orchestrator instruction ``argus-phase-6-001``.

Only the executor's own dispatch seam may ever request signing; research,
copyability, and every other non-executor CLI command have no signer/key
dependency at all. Proven two ways: (1) static import-graph inspection --
none of the non-executor packages import ``argus.executor.signing`` or
``argus.executor.dispatch``; (2) the fake/raising signer doubles behave
exactly as their names promise, with no real on-disk-keypair code path
anywhere in this package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from argus.executor.signing import FakeSigner, RaisingSigner, SignerNeverCalledError

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
)


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


def test_fake_signer_never_touches_real_key_material() -> None:
    signer = FakeSigner()
    assert signer.public_key == "FAKE_SIGNER_PUBLIC_KEY"
    signature = signer.sign_transaction(b"unsigned")
    assert signature == b"FAKE_SIGNATURE:unsigned"


def test_raising_signer_public_key_always_raises() -> None:
    with pytest.raises(SignerNeverCalledError):
        _ = RaisingSigner().public_key


def test_raising_signer_sign_transaction_always_raises() -> None:
    with pytest.raises(SignerNeverCalledError):
        RaisingSigner().sign_transaction(b"unsigned")


@pytest.mark.parametrize("package_name", _NON_EXECUTOR_PACKAGES)
def test_non_executor_package_has_no_signer_dependency(package_name: str) -> None:
    package_dir = _SRC / package_name
    if not package_dir.is_dir():
        pytest.skip(f"{package_name} package does not exist in this build")
    offenders = []
    for py_file in package_dir.rglob("*.py"):
        imported = _imported_module_names(py_file)
        if any("argus.executor" in name for name in imported):
            offenders.append(str(py_file.relative_to(_REPO_ROOT)))
    assert offenders == [], f"unauthorized signer/executor dependency in: {offenders}"


def test_cli_module_only_imports_executor_report_and_service_paths() -> None:
    """``argus/cli.py`` is allowed to import the read-only readiness
    reporting surface (``argus.executor.service``/``report``) for the
    ``executor readiness`` command, but never ``signing`` or ``dispatch``
    directly."""
    imported = _imported_module_names(_SRC / "cli.py")
    executor_imports = {name for name in imported if name.startswith("argus.executor")}
    for forbidden in ("argus.executor.signing", "argus.executor.dispatch"):
        assert forbidden not in executor_imports
