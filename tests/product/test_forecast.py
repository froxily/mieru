import datetime as dt
import math

import numpy as np
import pytest

from mieru.forecast.engine import LAG_COUNT, build_forecast, feature_row, next_period


def monthly_points(values: list[float], start: dt.date = dt.date(2020, 1, 1)) -> list[dict]:
    points = []
    period = start
    for value in values:
        points.append({"period": period.isoformat(), "revenue": value, "is_partial": False})
        period = next_period(period, "month")
    return points


def weekly_points(values: np.ndarray, start: dt.date = dt.date(2021, 1, 4)) -> list[dict]:
    return [{"period": (start + dt.timedelta(weeks=index)).isoformat(), "revenue": float(value), "is_partial": False} for index, value in enumerate(values)]


def test_short_history_is_gated_with_a_reason() -> None:
    result = build_forecast(monthly_points([100.0] * 10), "month")
    assert result["available"] is False
    assert "at least 18 complete months" in result["reason"]


def test_partial_periods_are_excluded_before_modelling() -> None:
    points = monthly_points([100.0 + index for index in range(20)])
    points[-1]["is_partial"] = True
    result = build_forecast(points, "month")
    assert len(result["history"]) == 19


def test_features_never_use_future_values() -> None:
    history = np.arange(30, dtype=float)
    poisoned = history.copy()
    index = 20
    poisoned[index:] = np.nan
    period = dt.date(2022, 9, 1)
    clean_row = feature_row(history, index, period, "month")
    poisoned_row = feature_row(poisoned, index, period, "month")
    assert clean_row == poisoned_row
    assert all(not math.isnan(value) for value in poisoned_row)
    assert clean_row[:LAG_COUNT] == [history[index - lag] for lag in range(1, LAG_COUNT + 1)]


def test_all_models_are_scored_on_identical_backtest_points() -> None:
    rng = np.random.default_rng(3)
    values = list(500 + 50 * np.sin(2 * np.pi * np.arange(36) / 12) + rng.normal(0, 10, 36))
    result = build_forecast(monthly_points(values), "month")
    assert result["available"] is True
    counts = {model["evaluation_points"] for model in result["models"]}
    assert len(counts) == 1
    assert {model["model"] for model in result["models"]} >= {"naive", "seasonal_naive", "moving_average", "ridge", "random_forest"}


def test_strong_seasonality_beats_the_naive_baseline() -> None:
    rng = np.random.default_rng(11)
    values = list(1000 + 300 * np.sin(2 * np.pi * np.arange(48) / 12) + rng.normal(0, 15, 48))
    result = build_forecast(monthly_points(values), "month")
    selected = next(model for model in result["models"] if model["model"] == result["selected_model"])
    assert result["selected_model"] != "naive"
    assert selected["skill_vs_naive"] > 0.3
    assert len(result["forecast"]) == 6


def test_intervals_are_withheld_when_residuals_are_scarce() -> None:
    values = list(np.linspace(100, 200, 20))
    result = build_forecast(monthly_points(values), "month")
    assert result["intervals"]["shown"] is False
    assert all(point["lower"] is None and point["upper"] is None for point in result["forecast"])
    assert "Not shown" in result["intervals"]["reason"]


def test_shown_intervals_are_approximately_calibrated() -> None:
    rng = np.random.default_rng(7)
    sigma = 30.0
    values = 500 + rng.normal(0, sigma, 200)
    result = build_forecast(weekly_points(values), "week")
    assert result["intervals"]["shown"] is True
    future = 500 + rng.normal(0, sigma, (2000, len(result["forecast"])))
    lower = np.array([point["lower"] for point in result["forecast"]])
    upper = np.array([point["upper"] for point in result["forecast"]])
    coverage = float(((future >= lower) & (future <= upper)).mean())
    assert 0.65 <= coverage <= 0.97
