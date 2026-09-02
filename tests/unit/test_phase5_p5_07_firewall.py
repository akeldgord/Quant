"""P5-07 (SPEC_BLOCKING) unit-level coverage: discovery firewall /
evidence-class separation -- MASTER_SPEC.md M7,
``argus.copyability.loaders.ContaminationFirewall``, orchestrator
instruction ``argus-phase-5-001``. The full end-to-end proof (persisted
``wallet_discovery_events`` provenance driving real exclusion of shadow
evidence, with selection-usable stats identical with/without contaminating
evidence present) is DB-backed integration coverage in
``tests/integration/test_phase5_persistence_and_report.py``; this module
proves the firewall's own decision primitive in isolation.
"""

from __future__ import annotations

import uuid

from argus.copyability.loaders import ContaminationFirewall


def test_contaminated_token_is_flagged() -> None:
    token_id = uuid.uuid4()
    firewall = ContaminationFirewall(contaminated_token_ids=frozenset({token_id}))
    assert firewall.is_contaminated(token_id) is True


def test_clean_token_is_not_flagged() -> None:
    contaminated = uuid.uuid4()
    clean = uuid.uuid4()
    firewall = ContaminationFirewall(contaminated_token_ids=frozenset({contaminated}))
    assert firewall.is_contaminated(clean) is False


def test_none_token_id_is_never_contaminated() -> None:
    firewall = ContaminationFirewall(contaminated_token_ids=frozenset({uuid.uuid4()}))
    assert firewall.is_contaminated(None) is False


def test_empty_firewall_flags_nothing() -> None:
    firewall = ContaminationFirewall(contaminated_token_ids=frozenset())
    assert firewall.is_contaminated(uuid.uuid4()) is False
