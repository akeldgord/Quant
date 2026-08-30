from __future__ import annotations

from argus.checkpoint import REPORTS_DIR, write_bundle


def test_write_bundle_produces_expected_sections() -> None:
    out_path = write_bundle(phase=0, checkpoint_text="STATUS: PASS\ntest checkpoint text")

    assert out_path.parent == REPORTS_DIR
    assert out_path.name == "orchestrator_bundle_phase_0.txt"
    text = out_path.read_text()

    assert "ARGUS ORCHESTRATOR REVIEW BUNDLE" in text
    assert "STATUS: PASS" in text
    assert "git status --porcelain" in text
    assert "git log -5 --oneline" in text
    assert "repository tree" in text
    assert "MASTER_SPEC hash" in text
    assert "BUILD_STATE.md" in text
    assert "DECISION_LOG.md" in text
