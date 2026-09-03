"""Unit tests for argus.prediction.evaluation (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): metric computation edge cases.
"""

from __future__ import annotations

from decimal import Decimal

from argus.prediction.evaluation import evaluate_predictions


def test_empty_test_set_returns_all_none() -> None:
    metrics = evaluate_predictions([], [], threshold=Decimal("0.5"))
    assert metrics.auc_roc is None
    assert metrics.log_loss is None
    assert metrics.brier_score is None
    assert metrics.accuracy_at_threshold is None


def test_single_class_test_set_has_no_auc_roc_but_has_other_metrics() -> None:
    metrics = evaluate_predictions([True, True, True], [0.6, 0.7, 0.8], threshold=Decimal("0.5"))
    assert metrics.auc_roc is None
    assert metrics.log_loss is not None
    assert metrics.brier_score is not None
    assert metrics.accuracy_at_threshold == Decimal(1)


def test_two_class_test_set_produces_a_real_auc_roc() -> None:
    y_true = [False, False, True, True]
    y_score = [0.1, 0.2, 0.8, 0.9]
    metrics = evaluate_predictions(y_true, y_score, threshold=Decimal("0.5"))
    assert metrics.auc_roc == Decimal(1)


def test_perfect_predictions_yield_minimal_brier_score() -> None:
    y_true = [False, True]
    y_score = [0.0, 1.0]
    metrics = evaluate_predictions(y_true, y_score, threshold=Decimal("0.5"))
    assert metrics.brier_score == Decimal(0)


def test_accuracy_at_threshold_respects_configured_threshold() -> None:
    y_true = [False, True]
    y_score = [0.4, 0.4]
    low_threshold = evaluate_predictions(y_true, y_score, threshold=Decimal("0.3"))
    high_threshold = evaluate_predictions(y_true, y_score, threshold=Decimal("0.6"))
    assert low_threshold.accuracy_at_threshold == Decimal("0.5")
    assert high_threshold.accuracy_at_threshold == Decimal("0.5")


def test_accuracy_at_threshold_counts_correctly() -> None:
    y_true = [False, False, True, True]
    y_score = [0.1, 0.9, 0.1, 0.9]
    metrics = evaluate_predictions(y_true, y_score, threshold=Decimal("0.5"))
    assert metrics.accuracy_at_threshold == Decimal("0.5")
