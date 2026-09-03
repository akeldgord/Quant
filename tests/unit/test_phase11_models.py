"""Unit tests for argus.prediction.models (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): thin scikit-learn fit/predict wrappers.
"""

from __future__ import annotations

from argus.prediction.models import (
    fit_predict_gradient_boosted_trees,
    fit_predict_logistic_regression,
    predict_base_rate,
)


def test_predict_base_rate_is_the_training_positive_rate() -> None:
    y_train = [True, True, False, False]
    scores = predict_base_rate(y_train, 3)
    assert scores == [0.5, 0.5, 0.5]


def test_predict_base_rate_is_deterministic_across_calls() -> None:
    y_train = [True, False, False]
    assert predict_base_rate(y_train, 5) == predict_base_rate(y_train, 5)


def test_predict_base_rate_empty_train_defaults_to_zero() -> None:
    assert predict_base_rate([], 2) == [0.0, 0.0]


def test_logistic_regression_separates_a_linearly_separable_dataset() -> None:
    x_train = [[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]]
    y_train = [False, False, False, True, True, True]
    x_test = [[0.05], [5.05]]
    scores = fit_predict_logistic_regression(x_train, y_train, x_test, regularized=False)
    assert scores[0] < 0.5
    assert scores[1] > 0.5


def test_regularized_logistic_regression_returns_valid_probabilities() -> None:
    x_train = [[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]]
    y_train = [False, False, False, True, True, True]
    x_test = [[0.05], [5.05]]
    scores = fit_predict_logistic_regression(x_train, y_train, x_test, regularized=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_gradient_boosted_trees_separates_a_simple_dataset() -> None:
    x_train = [[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]] * 3
    y_train = [False, False, False, True, True, True] * 3
    x_test = [[0.05], [5.05]]
    scores = fit_predict_gradient_boosted_trees(x_train, y_train, x_test)
    assert scores[0] < 0.5
    assert scores[1] > 0.5
