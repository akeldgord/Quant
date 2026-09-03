"""P6-17 (SPEC_BLOCKING): honest Phase 6 disposition -- MASTER_SPEC.md
section 82 (MAINNET CANARY), orchestrator instruction
``argus-phase-6-001``.

No claim of live readiness beyond actual evidence; ``LIVE_CANARY_PASSED``
and ``LIVE_ARMED`` are unconditionally ``False`` in every disposition
this module can produce, and ``LIVE_READY_SOFTWARE`` is never silently
``True`` from an empty criteria set.
"""

from __future__ import annotations

from argus.executor.report import build_disposition
from argus.executor.service import BUILD_HASH, build_phase6_disposition


def test_canary_and_armed_are_always_false_even_with_all_criteria_true() -> None:
    disposition = build_disposition(software_criteria={"a": True, "b": True})
    assert disposition.live_canary_passed is False
    assert disposition.live_armed is False


def test_live_ready_software_true_only_when_all_criteria_true() -> None:
    disposition = build_disposition(software_criteria={"a": True, "b": True})
    assert disposition.live_ready_software is True


def test_live_ready_software_false_when_any_criterion_false() -> None:
    disposition = build_disposition(software_criteria={"a": True, "b": False})
    assert disposition.live_ready_software is False


def test_empty_criteria_set_is_never_silently_ready() -> None:
    disposition = build_disposition(software_criteria={})
    assert disposition.live_ready_software is False


def test_as_dict_schema_has_the_required_keys() -> None:
    disposition = build_disposition(
        software_criteria={"x": True}, limitations=("something is unproven",)
    )
    payload = disposition.as_dict()
    assert set(payload.keys()) == {
        "LIVE_READY_SOFTWARE",
        "LIVE_CANARY_PASSED",
        "LIVE_ARMED",
        "software_criteria",
        "limitations",
    }
    assert payload["LIVE_CANARY_PASSED"] is False
    assert payload["LIVE_ARMED"] is False
    assert payload["limitations"] == ["something is unproven"]


def test_real_phase6_disposition_never_claims_canary_or_armed() -> None:
    disposition = build_phase6_disposition()
    assert disposition.live_canary_passed is False
    assert disposition.live_armed is False
    assert disposition.limitations != ()


def test_real_phase6_disposition_software_criteria_are_all_actual_booleans() -> None:
    disposition = build_phase6_disposition()
    assert disposition.software_criteria != {}
    for key, value in disposition.software_criteria.items():
        assert isinstance(value, bool), f"{key} is not a real bool: {value!r}"


def test_build_hash_is_a_real_sha256_hex_digest() -> None:
    assert len(BUILD_HASH) == 64
    int(BUILD_HASH, 16)


def test_build_disposition_never_mutates_input_criteria_dict() -> None:
    criteria = {"a": True}
    disposition = build_disposition(software_criteria=criteria)
    disposition.software_criteria["a"] = False
    assert criteria["a"] is True
