"""argus.prediction.models -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW): thin fit/predict wrappers over scikit-learn's implementations
of the models and single-feature-set baselines PHASE 11 names ("Do not
build a neural network until simpler models are convincingly beaten out of
sample" -- none of these is one). ``StandardScaler`` is fit ONLY on the
training split before either logistic regression variant -- fitting it on
the combined train+test data would leak test-set distribution information
into the transform; gradient-boosted trees need no scaling (tree splits are
threshold-based and scale-invariant).
"""

from __future__ import annotations

from typing import Final

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# Effectively unregularized (MASTER_SPEC's own "logistic regression",
# distinct from "regularized models"): a very large C makes sklearn's L2
# penalty term negligible without disabling it outright, which would cost
# numerical stability on near-separable data.
_UNREGULARIZED_C: Final[float] = 1e6
_REGULARIZED_C: Final[float] = 1.0
_MAX_ITER: Final[int] = 1000

_GRADIENT_BOOSTED_TREES_PARAMS: Final[dict] = {
    "n_estimators": 100,
    "max_depth": 3,
    "random_state": 0,
}


def predict_base_rate(y_train: list[bool], n_test: int) -> list[float]:
    """MASTER_SPEC's "random/base rate" baseline: the training split's own
    positive rate, predicted identically for every test row -- deterministic
    and reproducible (CORE-004), unlike a literal coin flip that would make
    an exact replay of the same run produce a different score."""
    positive_rate = (sum(1 for v in y_train if v) / len(y_train)) if y_train else 0.0
    return [positive_rate] * n_test


def fit_predict_logistic_regression(
    x_train: list[list[float]],
    y_train: list[bool],
    x_test: list[list[float]],
    *,
    regularized: bool,
) -> list[float]:
    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)
    x_test_scaled = scaler.transform(x_test)
    model = LogisticRegression(
        C=_REGULARIZED_C if regularized else _UNREGULARIZED_C, max_iter=_MAX_ITER
    )
    model.fit(x_train_scaled, [1 if v else 0 for v in y_train])
    return [float(row[1]) for row in model.predict_proba(x_test_scaled)]


def fit_predict_gradient_boosted_trees(
    x_train: list[list[float]], y_train: list[bool], x_test: list[list[float]]
) -> list[float]:
    model = GradientBoostingClassifier(**_GRADIENT_BOOSTED_TREES_PARAMS)
    model.fit(x_train, [1 if v else 0 for v in y_train])
    return [float(row[1]) for row in model.predict_proba(x_test)]
