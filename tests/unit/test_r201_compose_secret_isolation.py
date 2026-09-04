"""R2-01 (``argus-final-spec-recovery-002``) section 3.3: deployment/
permission proof that the ``api`` (and any other non-executor) Compose
service cannot read the operator-provisioned executor signing-key/arm
secrets path.

A real container runtime is unavailable in this sandbox (Docker daemon
unreachable -- the same environment block already recorded for FSR-03),
so this is the structural/compose-level permission proof the R2-01
instruction explicitly allows in that case: it parses the real
``compose.yaml`` this repository ships and proves, by configuration, that
only the ``executor`` service is ever given the host secrets volume
mount -- ``api`` has no such mount, so even if an operator's ``.env``
happened to set ``ARGUS_EXECUTOR_SIGNER_KEY_PATH`` (via the ``env_file``
both services share), the path would not resolve to a readable file
inside the ``api`` container's own filesystem, since Docker containers
never share a filesystem across services without an explicit volume
mount. The actual container-runtime-level check (attempting a real read
from inside a running ``api`` container) remains the FSR-03 PostgreSQL/
Docker-environment-blocked item -- not pretended here."""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_PATH = _REPO_ROOT / "compose.yaml"

_EXECUTOR_SECRETS_HOST_VAR = "ARGUS_EXECUTOR_HOST_SECRETS_DIR"
_EXECUTOR_SECRETS_CONTAINER_PATH = "/var/lib/argus/secrets"


def _load_compose() -> dict:
    return yaml.safe_load(_COMPOSE_PATH.read_text())


def test_executor_service_is_gated_behind_an_opt_in_profile() -> None:
    compose = _load_compose()
    executor = compose["services"]["executor"]
    assert executor.get("profiles") == ["executor"], (
        "the executor service must never start under a plain "
        "`docker compose up`/`make up` -- only an explicit "
        "`--profile executor` operator decision"
    )


def test_only_executor_service_mounts_the_host_secrets_directory() -> None:
    compose = _load_compose()
    services = compose["services"]
    offenders = []
    for name, definition in services.items():
        if name == "executor":
            continue
        for volume in definition.get("volumes", []):
            if _EXECUTOR_SECRETS_HOST_VAR in volume or _EXECUTOR_SECRETS_CONTAINER_PATH in volume:
                offenders.append(name)
    assert offenders == [], (
        f"non-executor service(s) {offenders} mount the operator secrets "
        "directory -- only `executor` may ever receive that mount"
    )

    executor_volumes = services["executor"].get("volumes", [])
    assert any(
        _EXECUTOR_SECRETS_HOST_VAR in v and v.rstrip().endswith(":ro") for v in executor_volumes
    ), "executor's own secrets mount must exist and be read-only"


def test_executor_service_exposes_no_inbound_port() -> None:
    compose = _load_compose()
    executor = compose["services"]["executor"]
    assert "ports" not in executor, (
        "nothing calls into the executor process; it must expose no port"
    )


def test_api_service_has_no_secrets_volume_mount_at_all() -> None:
    compose = _load_compose()
    api = compose["services"]["api"]
    assert "volumes" not in api, (
        "the api service must have no volume mounts at all -- it structurally "
        "cannot read a host directory it is never given access to, even if an "
        "operator's shared .env sets the executor's own path-shaped env var"
    )
