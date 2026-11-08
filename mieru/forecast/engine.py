import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

RANDOM_SEED: int = 42
MONTHLY_MIN_PERIODS: int = 18
WEEKLY_MIN_PERIODS: int = 30
MONTHLY_HOLDOUT: int = 6
WEEKLY_HOLDOUT: int = 8
MONTHLY_HORIZON: int = 6
WEEKLY_HORIZON: int = 8
MONTHLY_SEASON: int = 12
LAG_COUNT: int = 3
MOVING_AVERAGE_WINDOW: dict[str, int] = {"month": 3, "week": 4}
INTERVAL_LEVEL: float = 0.8
MIN_INTERVAL_RESIDUALS: int = 20
MIN_TRAINING_ROWS: int = 8
HOLDOUT_SHARE: float = 0.35
MIN_TRAIN_PERIODS: dict[str, int] = {"month": 12, "week": 16}
MODEL_LABELS: dict[str, str] = {
    "naive": "Naive (last value)",
    "seasonal_naive": "Seasonal naive (same period last year)",
    "moving_average": "Moving average",
    "ridge": "Ridge regression (lags + trend + seasonality)",
    "random_forest": "Random forest (lags + trend + seasonality)",
}
MODEL_COMPLEXITY: dict[str, int] = {"naive": 0, "seasonal_naive": 1, "moving_average": 2, "ridge": 3, "random_forest": 4}


@dataclass
class Series:
    periods: list[dt.date]
    values: np.ndarray
    granularity: str
    filled_gaps: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def season_length(self) -> int | None:
        return MONTHLY_SEASON if self.granularity == "month" else None


def next_period(period: dt.date, granularity: str) -> dt.date:
    if granularity == "week":
        return period + dt.timedelta(days=7)
    return (period.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def regularize(points: list[dict[str, Any]], granularity: str, value_key: str) -> Series:
    complete = [point for point in points if not point.get("is_partial") and point.get(value_key) is not None]
    if not complete:
        return Series(periods=[], values=np.array([]), granularity=granularity)
    by_period = {dt.date.fromisoformat(point["period"]): float(point[value_key]) for point in complete}
    first, last = min(by_period), max(by_period)
    periods: list[dt.date] = []
    values: list[float] = []
    filled = 0
    cursor = first
    while cursor <= last:
        periods.append(cursor)
        if cursor in by_period:
            values.append(by_period[cursor])
        else:
            values.append(0.0)
            filled += 1
        cursor = next_period(cursor, granularity)
    notes = [f"{filled} period(s) with no contributing rows were treated as zero."] if filled else []
    return Series(periods=periods, values=np.array(values, dtype=float), granularity=granularity, filled_gaps=filled, notes=notes)


def feature_row(history: np.ndarray, index: int, period: dt.date, granularity: str) -> list[float]:
    lags = [history[index - lag] for lag in range(1, LAG_COUNT + 1)]
    position = 2 * math.pi * ((period.month - 1) / 12 if granularity == "month" else (period.isocalendar().week - 1) / 52)
    return [*lags, float(index), math.sin(position), math.cos(position)]


def training_matrix(history: np.ndarray, periods: list[dt.date], granularity: str) -> tuple[np.ndarray, np.ndarray]:
    rows = [feature_row(history, index, periods[index], granularity) for index in range(LAG_COUNT, len(history))]
    return np.array(rows, dtype=float), history[LAG_COUNT:].astype(float)


def fit_regression(model_name: str, history: np.ndarray, periods: list[dt.date], granularity: str) -> Callable[[list[float]], float] | None:
    features, target = training_matrix(history, periods, granularity)
    if len(target) < MIN_TRAINING_ROWS:
        return None
    scaler = StandardScaler().fit(features)
    if model_name == "ridge":
        estimator = Ridge(alpha=1.0).fit(scaler.transform(features), target)
    else:
        estimator = RandomForestRegressor(n_estimators=100, max_depth=4, min_samples_leaf=2, random_state=RANDOM_SEED).fit(scaler.transform(features), target)
    return lambda row: float(estimator.predict(scaler.transform(np.array([row], dtype=float)))[0])


def forecast_path(model_name: str, history: np.ndarray, periods: list[dt.date], granularity: str, steps: int, season: int | None) -> list[float] | None:
    values = list(history.astype(float))
    calendar = list(periods)
    predictor = fit_regression(model_name, history, periods, granularity) if model_name in {"ridge", "random_forest"} else None
    if model_name in {"ridge", "random_forest"} and predictor is None:
        return None
    window = MOVING_AVERAGE_WINDOW[granularity]
    output: list[float] = []
    for _step in range(steps):
        upcoming = next_period(calendar[-1], granularity)
        index = len(values)
        if model_name == "naive":
            value = values[-1]
        elif model_name == "seasonal_naive":
            if season is None or index - season < 0:
                return None
            value = values[index - season]
        elif model_name == "moving_average":
            if len(values) < window:
                return None
            value = float(np.mean(values[-window:]))
        else:
            if len(values) < LAG_COUNT:
                return None
            value = predictor(feature_row(np.array(values), index, upcoming, granularity)) if predictor else None
            if value is None:
                return None
        output.append(max(0.0, value))
        values.append(output[-1])
        calendar.append(upcoming)
    return output


def backtest(series: Series, holdout: int, horizon: int) -> dict[str, Any]:
    total = len(series.values)
    origins = list(range(total - holdout, total))
    errors: dict[str, dict[int, list[float]]] = {name: {} for name in MODEL_LABELS}
    available: dict[str, bool] = {name: True for name in MODEL_LABELS}
    for origin in origins:
        history = series.values[:origin]
        periods = series.periods[:origin]
        steps = min(horizon, total - origin)
        actual = series.values[origin : origin + steps]
        for name in MODEL_LABELS:
            if not available[name]:
                continue
            path = forecast_path(name, history, periods, series.granularity, steps, series.season_length)
            if path is None:
                available[name] = False
                continue
            for step, (predicted, observed) in enumerate(zip(path, actual), start=1):
                errors[name].setdefault(step, []).append(float(observed - predicted))
    return {"origins": [series.periods[origin].isoformat() for origin in origins], "errors": {name: errors[name] for name in MODEL_LABELS if available[name]}}


def summarize_errors(errors_by_step: dict[int, list[float]]) -> dict[str, float | int]:
    flat = np.array([value for values in errors_by_step.values() for value in values], dtype=float)
    one_step = np.array(errors_by_step.get(1, []), dtype=float)
    return {
        "mae": float(np.mean(np.abs(flat))),
        "rmse": float(math.sqrt(np.mean(flat**2))),
        "one_step_mae": float(np.mean(np.abs(one_step))) if len(one_step) else float("nan"),
        "evaluation_points": int(len(flat)),
    }


def describe_range(counts: list[int]) -> str:
    if not counts:
        return "0"
    low, high = min(counts), max(counts)
    return str(low) if low == high else f"{low}–{high}"


def build_forecast(points: list[dict[str, Any]], granularity: str, value_key: str = "revenue") -> dict[str, Any]:
    working_points = points
    working_granularity = granularity
    notes: list[str] = []
    if granularity == "day":
        return {"available": False, "reason": "The data spans less than about two months; forecasting needs a longer history."}
    series = regularize(working_points, working_granularity, value_key)
    minimum = MONTHLY_MIN_PERIODS if working_granularity == "month" else WEEKLY_MIN_PERIODS
    if len(series.values) < minimum:
        unit = "months" if working_granularity == "month" else "weeks"
        return {
            "available": False,
            "reason": f"Forecasting needs at least {minimum} complete {unit} of history; this data has {len(series.values)}.",
        }
    if float(np.sum(series.values)) <= 0:
        return {"available": False, "reason": "The series has no positive values to forecast."}
    base_holdout = MONTHLY_HOLDOUT if working_granularity == "month" else WEEKLY_HOLDOUT
    horizon = MONTHLY_HORIZON if working_granularity == "month" else WEEKLY_HORIZON
    holdout = max(base_holdout, min(int(HOLDOUT_SHARE * len(series.values)), len(series.values) - MIN_TRAIN_PERIODS[working_granularity]))
    evaluation = backtest(series, holdout, horizon)
    common_points = None
    for errors_by_step in evaluation["errors"].values():
        counts = {step: len(values) for step, values in errors_by_step.items()}
        common_points = counts if common_points is None else {step: min(count, counts.get(step, 0)) for step, count in common_points.items()}
    scores = []
    for name, errors_by_step in evaluation["errors"].items():
        summary = summarize_errors(errors_by_step)
        scores.append({"model": name, "label": MODEL_LABELS[name], **summary})
    naive_mae = next((score["mae"] for score in scores if score["model"] == "naive"), None)
    for score in scores:
        score["skill_vs_naive"] = (1 - score["mae"] / naive_mae) if naive_mae else None
    scores.sort(key=lambda score: (score["mae"], MODEL_COMPLEXITY[score["model"]]))
    selected = scores[0]["model"]
    path = forecast_path(selected, series.values, series.periods, working_granularity, horizon, series.season_length) or []
    future_periods: list[dt.date] = []
    cursor = series.periods[-1]
    for _step in range(horizon):
        cursor = next_period(cursor, working_granularity)
        future_periods.append(cursor)
    selected_errors = evaluation["errors"][selected]
    intervals_available = all(len(selected_errors.get(step, [])) >= MIN_INTERVAL_RESIDUALS for step in range(1, horizon + 1))
    forecast_points = []
    for step, (period, value) in enumerate(zip(future_periods, path), start=1):
        lower = upper = None
        if intervals_available:
            radius = float(np.quantile(np.abs(selected_errors[step]), INTERVAL_LEVEL))
            lower, upper = max(0.0, value - radius), value + radius
        forecast_points.append({"period": period.isoformat(), "value": value, "lower": lower, "upper": upper, "step": step})
    residual_counts = {str(step): len(values) for step, values in selected_errors.items()}
    return {
        "available": True,
        "granularity": working_granularity,
        "history": [{"period": period.isoformat(), "value": float(value)} for period, value in zip(series.periods, series.values)],
        "forecast": forecast_points,
        "selected_model": selected,
        "selected_label": MODEL_LABELS[selected],
        "models": scores,
        "backtest": {
            "method": "Rolling-origin evaluation: each model is refitted at every origin in the holdout window using only earlier periods, "
            "and scored on the identical set of (origin, horizon) points.",
            "holdout_periods": holdout,
            "horizon": horizon,
            "origins": evaluation["origins"],
            "points_per_model": common_points,
        },
        "intervals": {
            "shown": intervals_available,
            "level": INTERVAL_LEVEL,
            "method": "Empirical quantile of absolute backtest errors at each horizon (split-conformal style).",
            "reason": None
            if intervals_available
            else f"Not shown: only {describe_range(list(residual_counts.values()))} backtest errors per horizon were available "
            f"(at least {MIN_INTERVAL_RESIDUALS} are needed for a calibrated {INTERVAL_LEVEL:.0%} interval).",
            "residuals_per_horizon": residual_counts,
        },
        "notes": notes + series.notes + [
            "Partial first/last periods are excluded before modelling.",
            "Forecasts extrapolate past patterns; promotions, stock-outs or market changes are not modelled.",
        ],
    }
