"""argus.prediction.evaluation -- MASTER_SPEC.md Phase 11 (PREDICT
INFORMED ORDER FLOW): pure metric computation wrapping ``sklearn.metrics``,
with explicit guards for the edge cases a small, temporally-split test set
produces -- AUC-ROC is undefined with only one class present in the test
labels; this module returns ``None`` for it rather than let sklearn raise,
never a fabricated or degenerate substitute value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


@dataclass(frozen=True)
class EvaluationMetrics:
    auc_roc: Decimal | None
    log_loss: Decimal | None
    brier_score: Decimal | None
    accuracy_at_threshold: Decimal | None


def evaluate_predictions(
    y_true: list[bool], y_score: list[float], *, threshold: Decimal
) -> EvaluationMetrics:
    if not y_true:
        return EvaluationMetrics(
            auc_roc=None, log_loss=None, brier_score=None, accuracy_at_threshold=None
        )

    y_true_int = [1 if v else 0 for v in y_true]

    auc_roc: Decimal | None = None
    if len(set(y_true_int)) == 2:
        auc_roc = Decimal(str(roc_auc_score(y_true_int, y_score)))

    # labels=[0, 1] explicitly: log_loss would otherwise raise when the
    # test split happens to contain only one class, since it cannot infer
    # the full label set from y_true alone in that case.
    loss = Decimal(str(log_loss(y_true_int, y_score, labels=[0, 1])))
    brier = Decimal(str(brier_score_loss(y_true_int, y_score)))

    threshold_float = float(threshold)
    predicted = [1 if score >= threshold_float else 0 for score in y_score]
    correct = sum(1 for p, t in zip(predicted, y_true_int, strict=True) if p == t)
    accuracy = Decimal(correct) / Decimal(len(y_true_int))

    return EvaluationMetrics(
        auc_roc=auc_roc, log_loss=loss, brier_score=brier, accuracy_at_threshold=accuracy
    )
