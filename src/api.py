import math
from datetime import date
from typing import Annotated, Any

import duckdb
from fastapi import FastAPI, HTTPException, Query

from src.analysis import METRICS_PATH, ON_TIME_BASELINE_DELAY_DAYS, load_metrics
from src.warehouse import DATABASE_PATH, connect_read_only

MONTH_PATTERN: str = r"^\d{4}-(0[1-9]|1[0-2])$"
SIMULATOR_MODEL_KEY: str = "model_1_severe_detractor"
SIGN_ONLY_NOTE: str = (
    "Model 1 encodes delivery delay as the binary flag is_sla_breached (delay_days > 0). Predictions depend only on "
    "the SIGN of delay_days (> 0 vs <= 0), not its magnitude: delay_days=1 and delay_days=30 return the same "
    "probability. For the empirical dose-response by exact delay, see sla_delay_day_profile in GET /summary."
)
COHORT_QUERY: str = """
    SELECT
        strftime(cohort_month, '%Y-%m') AS cohort_month,
        period_number,
        cohort_size,
        active_buyers,
        retention_rate_pct,
        cohort_gmv
    FROM mart_cohort_retention
    WHERE cohort_month BETWEEN ? AND ?
    ORDER BY cohort_month, period_number
"""

app = FastAPI(
    title="Olist Marketplace Analytics API",
    version="1.0.0",
    description="Cohort retention, seller concentration and SLA-breach risk simulation over the Olist marketplace warehouse.",
)


def read_metrics_or_503() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        raise HTTPException(status_code=503, detail="outputs/metrics_summary.json not found; run `python run.py` first.")
    return load_metrics(METRICS_PATH)


def parse_month_start(month_text: str) -> date:
    year_text, month_text_part = month_text.split("-")
    return date(int(year_text), int(month_text_part), 1)


def build_simulator_features(delay_days: int, order_gmv: float, freight_ratio: float, distance_km: float) -> dict[str, float]:
    return {
        "is_sla_breached": 1.0 if delay_days > 0 else 0.0,
        "log_order_gmv": math.log1p(order_gmv),
        "freight_ratio": min(max(freight_ratio, 0.0), 1.0),
        "log_distance_km": math.log1p(distance_km),
    }


def predict_probability(prediction_spec: dict[str, Any], features: dict[str, float]) -> float:
    linear_predictor = prediction_spec["intercept"] + sum(
        prediction_spec["coefficients"][feature] * features[feature] for feature in prediction_spec["feature_order"]
    )
    return 1.0 / (1.0 + math.exp(-linear_predictor))


def observed_detractor_rate(metrics: dict[str, Any], delay_days: int) -> float | None:
    for day_row in metrics.get("sla_delay_day_profile", []):
        if day_row["sla_delay_days"] == delay_days:
            return day_row["severe_detractor"]["rate_pct"]
    return None


@app.get("/")
def get_index() -> dict[str, Any]:
    return {
        "service": app.title,
        "endpoints": ["/summary", "/cohorts?start_month=2017-01&end_month=2018-08", "/sla-simulator?delay_days=3", "/docs"],
    }


@app.get("/summary")
def get_summary() -> dict[str, Any]:
    return read_metrics_or_503()


@app.get("/cohorts")
def get_cohorts(
    start_month: Annotated[str, Query(pattern=MONTH_PATTERN, description="First cohort month, YYYY-MM")] = "2017-01",
    end_month: Annotated[str, Query(pattern=MONTH_PATTERN, description="Last cohort month, YYYY-MM")] = "2018-08",
) -> dict[str, Any]:
    start_date = parse_month_start(start_month)
    end_date = parse_month_start(end_month)
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_month must be on or before end_month.")
    if not DATABASE_PATH.exists():
        raise HTTPException(status_code=503, detail="data/marketplace.duckdb not found; run `python run.py` first.")
    try:
        with connect_read_only() as connection:
            cursor = connection.execute(COHORT_QUERY, [start_date, end_date])
            column_names = [column[0] for column in cursor.description]
            records = [dict(zip(column_names, row)) for row in cursor.fetchall()]
    except duckdb.Error as error:
        raise HTTPException(status_code=503, detail=f"Warehouse unavailable: {error}") from error
    return {
        "start_month": start_month,
        "end_month": end_month,
        "cohort_count": len({record["cohort_month"] for record in records}),
        "row_count": len(records),
        "rows": records,
    }


@app.get("/sla-simulator")
def simulate_sla_breach(
    delay_days: Annotated[int, Query(ge=-120, le=200, description="Delivered minus promised date, in days")] = 3,
    order_gmv: Annotated[float, Query(gt=0.0, le=1_000_000.0, description="Order GMV in BRL (price + freight)")] = 120.0,
    freight_ratio: Annotated[float, Query(ge=0.0, le=1.0, description="Freight / order GMV")] = 0.15,
    distance_km: Annotated[float, Query(ge=0.0, le=5_000.0, description="Seller-to-customer distance in km")] = 350.0,
) -> dict[str, Any]:
    metrics = read_metrics_or_503()
    prediction_spec = metrics["logistic_models"][SIMULATOR_MODEL_KEY]["prediction_spec"]
    scenario_features = build_simulator_features(delay_days, order_gmv, freight_ratio, distance_km)
    baseline_features = build_simulator_features(ON_TIME_BASELINE_DELAY_DAYS, order_gmv, freight_ratio, distance_km)
    scenario_probability = predict_probability(prediction_spec, scenario_features)
    baseline_probability = predict_probability(prediction_spec, baseline_features)
    scenario_odds = scenario_probability / (1.0 - scenario_probability)
    baseline_odds = baseline_probability / (1.0 - baseline_probability)
    return {
        "model": SIMULATOR_MODEL_KEY,
        "inputs": {
            "delay_days": delay_days,
            "order_gmv": order_gmv,
            "freight_ratio": freight_ratio,
            "distance_km": distance_km,
        },
        "scenario": {
            "delay_days": delay_days,
            "is_sla_breached": int(scenario_features["is_sla_breached"]),
            "model_features": scenario_features,
            "predicted_severe_detractor_probability": scenario_probability,
            "observed_severe_detractor_rate_pct_at_this_delay": observed_detractor_rate(metrics, delay_days),
        },
        "on_time_baseline": {
            "delay_days": ON_TIME_BASELINE_DELAY_DAYS,
            "is_sla_breached": int(baseline_features["is_sla_breached"]),
            "model_features": baseline_features,
            "predicted_severe_detractor_probability": baseline_probability,
        },
        "absolute_risk_lift_pp": 100.0 * (scenario_probability - baseline_probability),
        "relative_risk_vs_baseline": scenario_probability / baseline_probability,
        "odds_ratio_vs_baseline": scenario_odds / baseline_odds,
        "model_note": SIGN_ONLY_NOTE,
    }
