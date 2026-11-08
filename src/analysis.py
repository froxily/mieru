import json
import math
from collections.abc import Sequence
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from src.data import PROJECT_ROOT, SOURCE_BASE_URL
from src.warehouse import connect_read_only

RANDOM_SEED: int = 42
OUTPUT_DIR: Path = PROJECT_ROOT / "outputs"
METRICS_PATH: Path = OUTPUT_DIR / "metrics_summary.json"
ALPHA: float = 0.05
Z_CRITICAL: float = float(stats.norm.ppf(1.0 - ALPHA / 2.0))
GINI_BOOTSTRAP_RESAMPLES: int = 2000
DAY_PROFILE_MIN: int = -15
DAY_PROFILE_MAX: int = 15
ON_TIME_BASELINE_DELAY_DAYS: int = -2
FIXED_EFFECTS_WINDOW: tuple[str, str] = ("2017-01-01", "2018-08-01")
SELLER_MIN_ORDERS_FOR_CORRELATION: int = 20
TRACKED_PACKAGES: tuple[str, ...] = ("duckdb", "pandas", "numpy", "scipy", "statsmodels", "matplotlib", "fastapi")

SLA_BUCKET_ORDER: tuple[str, ...] = (
    "1. >7d Early",
    "2. 1-7d Early",
    "3. On Time (Day 0)",
    "4. 1-3d Late",
    "5. 4-7d Late",
    "6. >7d Late",
)
PARETO_TIER_ORDER: tuple[str, ...] = ("Top 10% Sellers", "Middle 40% Sellers", "Bottom 50% Long-Tail")
MODEL_COVARIATE_COLUMNS: tuple[str, ...] = ("review_score", "order_gmv", "freight_ratio", "delivery_distance_km")
LOGIT_CONTROL_FEATURES: tuple[str, ...] = ("log_order_gmv", "freight_ratio", "log_distance_km")
MODEL_1_FEATURES: tuple[str, ...] = ("is_sla_breached", *LOGIT_CONTROL_FEATURES)
MODEL_2B_FEATURES: tuple[str, ...] = ("is_severe_detractor", *LOGIT_CONTROL_FEATURES)
FEATURE_PREPROCESSING: dict[str, str] = {
    "is_sla_breached": "1.0 if delay_days > 0 else 0.0 (binary breach flag; delay magnitude is not modelled)",
    "is_severe_detractor": "1.0 if review_score <= 2.0 else 0.0",
    "log_order_gmv": "numpy.log1p(order_gmv)",
    "freight_ratio": "clip(freight_ratio, 0.0, 1.0)",
    "log_distance_km": "numpy.log1p(distance_km)",
}

ORDER_QUERY: str = """
    SELECT
        order_id,
        customer_unique_id,
        customer_state,
        purchase_month,
        order_purchase_timestamp,
        customer_order_seq,
        customer_total_orders,
        is_repeat_buyer,
        is_repeat_after_delivery,
        is_repeat_within_180d_after_delivery,
        item_count,
        seller_count,
        order_gmv,
        freight_ratio,
        review_score,
        actual_delivery_days,
        promised_sla_days,
        sla_delay_days,
        is_sla_breached,
        is_severe_detractor,
        is_five_star,
        sla_delay_bucket,
        delivery_distance_km
    FROM mart_order_fulfillment
"""


def to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        return as_float if math.isfinite(as_float) else None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return value


def log10_from_natural_log(natural_log_value: float) -> float:
    return natural_log_value / math.log(10.0)


def format_p_value(p_value: float, log10_p_value: float) -> str:
    if p_value >= 1e-4:
        return f"{p_value:.4f}"
    return f"< 1e{math.floor(log10_p_value) + 1}" if math.isfinite(log10_p_value) else "< 1e-300"


def proportion_summary(events: int, trials: int) -> dict[str, float | int | None]:
    if trials == 0:
        return {"n": 0, "events": 0, "rate_pct": None, "ci_low_pct": None, "ci_high_pct": None}
    ci_low, ci_high = proportion_confint(events, trials, alpha=ALPHA, method="wilson")
    return {
        "n": int(trials),
        "events": int(events),
        "rate_pct": 100.0 * events / trials,
        "ci_low_pct": 100.0 * float(ci_low),
        "ci_high_pct": 100.0 * float(ci_high),
    }


def mean_confidence_interval(values: np.ndarray) -> dict[str, float | int | None]:
    sample_size = len(values)
    if sample_size < 2:
        return {"n": int(sample_size), "mean": float(values.mean()) if sample_size else None, "ci_low": None, "ci_high": None}
    sample_mean = float(values.mean())
    half_width = float(stats.t.ppf(1.0 - ALPHA / 2.0, sample_size - 1) * values.std(ddof=1) / math.sqrt(sample_size))
    return {"n": int(sample_size), "mean": sample_mean, "ci_low": sample_mean - half_width, "ci_high": sample_mean + half_width}


def two_proportion_tests(
    treated_events: int, treated_trials: int, control_events: int, control_trials: int
) -> dict[str, float | None]:
    treated_rate = treated_events / treated_trials
    control_rate = control_events / control_trials
    difference_se = math.sqrt(
        treated_rate * (1.0 - treated_rate) / treated_trials + control_rate * (1.0 - control_rate) / control_trials
    )
    contingency = np.array(
        [[treated_events, treated_trials - treated_events], [control_events, control_trials - control_events]]
    )
    chi2_statistic, chi2_p_value, degrees_of_freedom, _ = stats.chi2_contingency(contingency, correction=True)
    chi2_log10_p = log10_from_natural_log(float(stats.chi2.logsf(chi2_statistic, degrees_of_freedom)))
    result: dict[str, float | None] = {
        "absolute_difference_pp": 100.0 * (treated_rate - control_rate),
        "absolute_difference_ci_low_pp": 100.0 * (treated_rate - control_rate - Z_CRITICAL * difference_se),
        "absolute_difference_ci_high_pp": 100.0 * (treated_rate - control_rate + Z_CRITICAL * difference_se),
        "relative_risk": None,
        "relative_risk_ci_low": None,
        "relative_risk_ci_high": None,
        "unadjusted_odds_ratio": None,
        "chi2_statistic_yates": float(chi2_statistic),
        "chi2_degrees_of_freedom": int(degrees_of_freedom),
        "chi2_p_value": float(chi2_p_value),
        "chi2_log10_p_value": chi2_log10_p,
        "chi2_p_value_display": format_p_value(float(chi2_p_value), chi2_log10_p),
    }
    if treated_events > 0 and control_events > 0:
        relative_risk = treated_rate / control_rate
        log_rr_se = math.sqrt(1.0 / treated_events - 1.0 / treated_trials + 1.0 / control_events - 1.0 / control_trials)
        result["relative_risk"] = relative_risk
        result["relative_risk_ci_low"] = math.exp(math.log(relative_risk) - Z_CRITICAL * log_rr_se)
        result["relative_risk_ci_high"] = math.exp(math.log(relative_risk) + Z_CRITICAL * log_rr_se)
    if 0 < treated_events < treated_trials and 0 < control_events < control_trials:
        result["unadjusted_odds_ratio"] = (treated_events / (treated_trials - treated_events)) / (
            control_events / (control_trials - control_events)
        )
    return result


def load_orders(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    orders = connection.execute(ORDER_QUERY).df()
    orders["purchase_month"] = pd.to_datetime(orders["purchase_month"])
    orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"])
    return orders


def compute_platform_kpis(orders: pd.DataFrame) -> dict[str, Any]:
    first_orders = orders.loc[orders["customer_order_seq"] == 1]
    repeat_customers = orders.loc[orders["customer_total_orders"] >= 2]
    purchase_days_per_repeat_customer = (
        repeat_customers.assign(purchase_date=repeat_customers["order_purchase_timestamp"].dt.normalize())
        .groupby("customer_unique_id")["purchase_date"]
        .nunique()
    )
    same_day_only_repeaters = int((purchase_days_per_repeat_customer == 1).sum())
    return {
        "delivered_orders": int(len(orders)),
        "unique_customers": int(orders["customer_unique_id"].nunique()),
        "purchase_window_start": orders["order_purchase_timestamp"].min(),
        "purchase_window_end": orders["order_purchase_timestamp"].max(),
        "total_gmv_brl": float(orders["order_gmv"].sum()),
        "average_order_value_brl": float(orders["order_gmv"].mean()),
        "median_order_value_brl": float(orders["order_gmv"].median()),
        "sla_breach_rate_pct": 100.0 * float(orders["is_sla_breached"].mean()),
        "median_actual_delivery_days": float(orders["actual_delivery_days"].median()),
        "median_promised_sla_days": float(orders["promised_sla_days"].median()),
        "median_sla_delay_days": float(orders["sla_delay_days"].median()),
        "mean_review_score": float(orders["review_score"].mean()),
        "five_star_rate_pct": 100.0 * float(orders["is_five_star"].dropna().mean()),
        "severe_detractor_rate_pct": 100.0 * float(orders["is_severe_detractor"].dropna().mean()),
        "customer_repeat_purchase_rate_pct": 100.0 * float(first_orders["is_repeat_buyer"].mean()),
        "customer_repeat_after_first_delivery_rate_pct": 100.0 * float(first_orders["is_repeat_after_delivery"].mean()),
        "customer_repeat_within_180d_of_first_delivery_rate_pct": 100.0
        * float(first_orders["is_repeat_within_180d_after_delivery"].dropna().mean()),
        "first_orders_with_full_180d_followup": int(first_orders["is_repeat_within_180d_after_delivery"].notna().sum()),
        "single_purchase_customer_share_pct": 100.0 * (1.0 - float(first_orders["is_repeat_buyer"].mean())),
        "repeat_customers": int(first_orders["is_repeat_buyer"].sum()),
        "repeat_customers_with_all_orders_same_day": same_day_only_repeaters,
    }


def compare_review_scores(orders: pd.DataFrame) -> dict[str, Any]:
    reviewed = orders.dropna(subset=["review_score"])
    breached = reviewed.loc[reviewed["sla_delay_days"] > 0, "review_score"].to_numpy(dtype=float)
    on_time = reviewed.loc[reviewed["sla_delay_days"] <= 0, "review_score"].to_numpy(dtype=float)
    breached_variance_of_mean = breached.var(ddof=1) / len(breached)
    on_time_variance_of_mean = on_time.var(ddof=1) / len(on_time)
    standard_error = math.sqrt(breached_variance_of_mean + on_time_variance_of_mean)
    welch_degrees_of_freedom = (breached_variance_of_mean + on_time_variance_of_mean) ** 2 / (
        breached_variance_of_mean**2 / (len(breached) - 1) + on_time_variance_of_mean**2 / (len(on_time) - 1)
    )
    t_critical = float(stats.t.ppf(1.0 - ALPHA / 2.0, welch_degrees_of_freedom))
    mean_difference = float(breached.mean() - on_time.mean())
    welch_test = stats.ttest_ind(breached, on_time, equal_var=False)
    welch_log10_p = log10_from_natural_log(
        math.log(2.0) + float(stats.t.logsf(abs(float(welch_test.statistic)), welch_degrees_of_freedom))
    )
    mann_whitney = stats.mannwhitneyu(breached, on_time, alternative="two-sided")
    pooled_sd = math.sqrt(
        ((len(breached) - 1) * breached.var(ddof=1) + (len(on_time) - 1) * on_time.var(ddof=1))
        / (len(breached) + len(on_time) - 2)
    )
    return {
        "definition": "On-Time = sla_delay_days <= 0; SLA Breached = sla_delay_days > 0; reviewed delivered orders only",
        "on_time": mean_confidence_interval(on_time),
        "sla_breached": mean_confidence_interval(breached),
        "mean_difference_breached_minus_on_time": mean_difference,
        "mean_difference_ci_low": mean_difference - t_critical * standard_error,
        "mean_difference_ci_high": mean_difference + t_critical * standard_error,
        "cohens_d": mean_difference / pooled_sd,
        "welch_t_statistic": float(welch_test.statistic),
        "welch_degrees_of_freedom": float(welch_degrees_of_freedom),
        "welch_p_value": float(welch_test.pvalue),
        "welch_log10_p_value": welch_log10_p,
        "welch_p_value_display": format_p_value(float(welch_test.pvalue), welch_log10_p),
        "mann_whitney_u_statistic": float(mann_whitney.statistic),
        "mann_whitney_p_value": float(mann_whitney.pvalue),
        "common_language_effect_size": float(mann_whitney.statistic) / (len(breached) * len(on_time)),
    }


def compare_severe_detractor_rates(orders: pd.DataFrame) -> dict[str, Any]:
    reviewed = orders.dropna(subset=["is_severe_detractor"])
    breached_mask = reviewed["sla_delay_days"] > 0
    breached_events = int(reviewed.loc[breached_mask, "is_severe_detractor"].sum())
    breached_trials = int(breached_mask.sum())
    on_time_events = int(reviewed.loc[~breached_mask, "is_severe_detractor"].sum())
    on_time_trials = int((~breached_mask).sum())
    return {
        "definition": "severe detractor = order-level mean review_score <= 2.0",
        "on_time": proportion_summary(on_time_events, on_time_trials),
        "sla_breached": proportion_summary(breached_events, breached_trials),
        **two_proportion_tests(breached_events, breached_trials, on_time_events, on_time_trials),
    }


def compare_repeat_purchase(orders: pd.DataFrame) -> dict[str, Any]:
    first_orders = orders.loc[orders["customer_order_seq"] == 1]
    breached_mask = first_orders["sla_delay_days"] > 0
    by_bucket: list[dict[str, Any]] = []
    bucket_contingency: list[list[int]] = []
    for bucket in SLA_BUCKET_ORDER:
        bucket_orders = first_orders.loc[first_orders["sla_delay_bucket"] == bucket]
        repeat_events = int(bucket_orders["is_repeat_buyer"].sum())
        by_bucket.append(
            {
                "sla_delay_bucket": bucket,
                "repeat_buyer": proportion_summary(repeat_events, len(bucket_orders)),
                "repeat_within_180d_after_first_delivery": proportion_summary(
                    int(bucket_orders["is_repeat_within_180d_after_delivery"].dropna().sum()),
                    int(bucket_orders["is_repeat_within_180d_after_delivery"].notna().sum()),
                ),
            }
        )
        bucket_contingency.append([repeat_events, len(bucket_orders) - repeat_events])
    bucket_chi2, bucket_p_value, bucket_dof, _ = stats.chi2_contingency(np.array(bucket_contingency))
    comparisons: dict[str, Any] = {}
    for outcome in ("is_repeat_buyer", "is_repeat_within_180d_after_delivery"):
        eligible = first_orders.dropna(subset=[outcome])
        eligible_breached = eligible["sla_delay_days"] > 0
        breached_events = int(eligible.loc[eligible_breached, outcome].sum())
        on_time_events = int(eligible.loc[~eligible_breached, outcome].sum())
        breached_trials = int(eligible_breached.sum())
        on_time_trials = int((~eligible_breached).sum())
        comparisons[outcome] = {
            "on_time": proportion_summary(on_time_events, on_time_trials),
            "sla_breached": proportion_summary(breached_events, breached_trials),
            **two_proportion_tests(breached_events, breached_trials, on_time_events, on_time_trials),
        }
    return {
        "definition": "first delivered order per customer_unique_id (customer_order_seq == 1); is_repeat_buyer = >= 2 delivered "
        "orders; is_repeat_within_180d_after_delivery = a new order placed within 180 days AFTER the first order was delivered "
        "(only first orders with >= 180 days of observable follow-up)",
        "first_order_count": int(len(first_orders)),
        "on_time_vs_breached": comparisons,
        "by_sla_delay_bucket": by_bucket,
        "bucket_independence_chi2": float(bucket_chi2),
        "bucket_independence_dof": int(bucket_dof),
        "bucket_independence_p_value": float(bucket_p_value),
    }


def build_sla_delay_day_profile(orders: pd.DataFrame) -> list[dict[str, Any]]:
    profile: list[dict[str, Any]] = []
    for delay_day in range(DAY_PROFILE_MIN, DAY_PROFILE_MAX + 1):
        day_orders = orders.loc[orders["sla_delay_days"] == delay_day]
        reviewed_scores = day_orders["review_score"].dropna().to_numpy(dtype=float)
        detractor_flags = day_orders["is_severe_detractor"].dropna()
        profile.append(
            {
                "sla_delay_days": delay_day,
                "orders": int(len(day_orders)),
                "review_score": mean_confidence_interval(reviewed_scores),
                "severe_detractor": proportion_summary(int(detractor_flags.sum()), int(len(detractor_flags))),
            }
        )
    return profile


def build_sla_bucket_profile(orders: pd.DataFrame) -> list[dict[str, Any]]:
    profile: list[dict[str, Any]] = []
    for bucket in SLA_BUCKET_ORDER:
        bucket_orders = orders.loc[orders["sla_delay_bucket"] == bucket]
        detractor_flags = bucket_orders["is_severe_detractor"].dropna()
        five_star_flags = bucket_orders["is_five_star"].dropna()
        profile.append(
            {
                "sla_delay_bucket": bucket,
                "orders": int(len(bucket_orders)),
                "order_share_pct": 100.0 * len(bucket_orders) / len(orders),
                "review_score": mean_confidence_interval(bucket_orders["review_score"].dropna().to_numpy(dtype=float)),
                "severe_detractor": proportion_summary(int(detractor_flags.sum()), int(len(detractor_flags))),
                "five_star": proportion_summary(int(five_star_flags.sum()), int(len(five_star_flags))),
                "mean_actual_delivery_days": float(bucket_orders["actual_delivery_days"].mean()),
            }
        )
    return profile


def day_detractor_counts(reviewed: pd.DataFrame, delay_day: int) -> tuple[int, int]:
    day_flags = reviewed.loc[reviewed["sla_delay_days"] == delay_day, "is_severe_detractor"]
    return int(day_flags.sum()), int(len(day_flags))


def estimate_sla_threshold_discontinuity(orders: pd.DataFrame) -> dict[str, Any]:
    reviewed = orders.dropna(subset=["is_severe_detractor"])
    minus_one = day_detractor_counts(reviewed, -1)
    day_zero = day_detractor_counts(reviewed, 0)
    plus_one = day_detractor_counts(reviewed, 1)
    threshold_jump = two_proportion_tests(*plus_one, *day_zero)
    placebo_jump = two_proportion_tests(*day_zero, *minus_one)
    placebo_pp = placebo_jump["absolute_difference_pp"]
    return {
        "design": "Local comparison of orders delivered exactly on the promised date (Day 0) vs one day late (Day +1); "
        "the Day -1 vs Day 0 step is a placebo threshold where no SLA status changes.",
        "day_minus_1_severe_detractor": proportion_summary(*minus_one),
        "day_0_severe_detractor": proportion_summary(*day_zero),
        "day_plus_1_severe_detractor": proportion_summary(*plus_one),
        "threshold_jump_day0_to_plus1": threshold_jump,
        "placebo_jump_minus1_to_day0": placebo_jump,
        "threshold_to_placebo_jump_ratio": (
            threshold_jump["absolute_difference_pp"] / placebo_pp if placebo_pp and abs(placebo_pp) > 1e-9 else None
        ),
    }


def build_model_frame(orders: pd.DataFrame, extra_required_columns: Sequence[str]) -> pd.DataFrame:
    required_columns = list(dict.fromkeys([*MODEL_COVARIATE_COLUMNS, *extra_required_columns]))
    model_frame = orders.dropna(subset=required_columns).copy()
    model_frame["log_order_gmv"] = np.log1p(model_frame["order_gmv"].astype(float))
    model_frame["log_distance_km"] = np.log1p(model_frame["delivery_distance_km"].astype(float))
    model_frame["freight_ratio"] = model_frame["freight_ratio"].astype(float).clip(0.0, 1.0)
    return model_frame


def separation_diagnostics(model_frame: pd.DataFrame, outcome: str, features: Sequence[str]) -> dict[str, int]:
    diagnostics: dict[str, int] = {}
    for feature in features:
        if set(model_frame[feature].dropna().unique()) <= {0, 1}:
            crosstab = pd.crosstab(model_frame[feature], model_frame[outcome])
            diagnostics[f"{feature}_min_cell_count"] = int(crosstab.to_numpy().min()) if crosstab.shape == (2, 2) else 0
    return diagnostics


def roc_auc(predicted_probability: np.ndarray, response: np.ndarray) -> float:
    positives = predicted_probability[response == 1]
    negatives = predicted_probability[response == 0]
    u_statistic = stats.mannwhitneyu(positives, negatives, alternative="two-sided").statistic
    return float(u_statistic) / (len(positives) * len(negatives))


def exposure_counterfactual(
    result: Any, design: pd.DataFrame, response: pd.Series, exposure: str
) -> dict[str, float | int]:
    exposed_design = design.copy()
    unexposed_design = design.copy()
    exposed_design[exposure] = 1.0
    unexposed_design[exposure] = 0.0
    probability_gap = np.asarray(result.predict(exposed_design)) - np.asarray(result.predict(unexposed_design))
    exposed_mask = design[exposure].to_numpy() == 1.0
    excess_events = float(probability_gap[exposed_mask].sum())
    marginal_effects = result.get_margeff(at="overall", method="dydx", dummy=True).summary_frame(alpha=ALPHA)
    exposure_effect = marginal_effects.loc[exposure]
    return {
        "average_marginal_effect_pp": 100.0 * float(exposure_effect.iloc[0]),
        "average_marginal_effect_ci_low_pp": 100.0 * float(exposure_effect.iloc[4]),
        "average_marginal_effect_ci_high_pp": 100.0 * float(exposure_effect.iloc[5]),
        "average_counterfactual_risk_difference_pp": 100.0 * float(probability_gap.mean()),
        "exposed_orders": int(exposed_mask.sum()),
        "excess_events_among_exposed": excess_events,
        "excess_events_share_of_all_events_pct": 100.0 * excess_events / float(response.sum()),
    }


def fit_logit(
    model_frame: pd.DataFrame, outcome: str, features: Sequence[str], exposure: str, description: str
) -> dict[str, Any]:
    design = sm.add_constant(model_frame[list(features)].astype(float), has_constant="add")
    response = model_frame[outcome].astype(float)
    result = sm.Logit(response, design).fit(disp=0, maxiter=200, cov_type="HC0")
    confidence_bounds = result.conf_int(alpha=ALPHA)
    terms = [
        {
            "term": term,
            "coef_log_odds": float(result.params[term]),
            "std_err_hc0": float(result.bse[term]),
            "z_stat": float(result.tvalues[term]),
            "p_value": float(result.pvalues[term]),
            "odds_ratio": math.exp(float(result.params[term])),
            "or_ci_low": math.exp(float(confidence_bounds.loc[term, 0])),
            "or_ci_high": math.exp(float(confidence_bounds.loc[term, 1])),
        }
        for term in design.columns
    ]
    predicted_probability = np.asarray(result.predict(design))
    return {
        "description": description,
        "outcome": outcome,
        "exposure": exposure,
        "estimator": "statsmodels.discrete.discrete_model.Logit (Newton-Raphson MLE)",
        "covariance_type": "HC0",
        "n_obs": int(result.nobs),
        "n_events": int(response.sum()),
        "event_rate_pct": 100.0 * float(response.mean()),
        "converged": bool(result.mle_retvals.get("converged", False)),
        "iterations": int(result.mle_retvals.get("iterations", -1)),
        "pseudo_r2_mcfadden": float(result.prsquared),
        "log_likelihood": float(result.llf),
        "log_likelihood_null": float(result.llnull),
        "llr_p_value": float(result.llr_pvalue),
        "aic": float(result.aic),
        "roc_auc": roc_auc(predicted_probability, response.to_numpy()),
        "separation_diagnostics": separation_diagnostics(model_frame, outcome, features),
        "terms": terms,
        "exposure_effect": exposure_counterfactual(result, design, response, exposure),
        "prediction_spec": {
            "link": "logit",
            "formula": "p = 1 / (1 + exp(-(intercept + sum(coefficients[f] * x[f] for f in feature_order))))",
            "intercept": float(result.params["const"]),
            "feature_order": list(features),
            "coefficients": {feature: float(result.params[feature]) for feature in features},
            "preprocessing": {feature: FEATURE_PREPROCESSING[feature] for feature in features},
        },
    }


def fit_fixed_effects_robustness(orders: pd.DataFrame) -> dict[str, Any]:
    window_start, window_end = (pd.Timestamp(month) for month in FIXED_EFFECTS_WINDOW)
    model_frame = build_model_frame(orders, ["is_severe_detractor"])
    model_frame = model_frame.loc[model_frame["purchase_month"].between(window_start, window_end)]
    fixed_effect_dummies = pd.get_dummies(
        model_frame[["customer_state"]].astype(str).assign(
            purchase_month=model_frame["purchase_month"].dt.strftime("%Y-%m")
        ),
        prefix=["state", "month"],
        drop_first=True,
        dtype=float,
    )
    base_design = sm.add_constant(model_frame[[*MODEL_1_FEATURES, "item_count"]].astype(float), has_constant="add")
    design = pd.concat([base_design, fixed_effect_dummies], axis=1)
    response = model_frame["is_severe_detractor"].astype(float)
    result = sm.Logit(response, design).fit(disp=0, maxiter=200, cov_type="HC0")
    confidence_bounds = result.conf_int(alpha=ALPHA)
    return {
        "description": "Model 1 + item_count + customer-state fixed effects + purchase-month fixed effects "
        f"(purchase months {FIXED_EFFECTS_WINDOW[0][:7]}..{FIXED_EFFECTS_WINDOW[1][:7]})",
        "covariance_type": "HC0",
        "n_obs": int(result.nobs),
        "n_fixed_effect_dummies": int(fixed_effect_dummies.shape[1]),
        "converged": bool(result.mle_retvals.get("converged", False)),
        "pseudo_r2_mcfadden": float(result.prsquared),
        "is_sla_breached_odds_ratio": math.exp(float(result.params["is_sla_breached"])),
        "is_sla_breached_or_ci_low": math.exp(float(confidence_bounds.loc["is_sla_breached", 0])),
        "is_sla_breached_or_ci_high": math.exp(float(confidence_bounds.loc["is_sla_breached", 1])),
        "is_sla_breached_p_value": float(result.pvalues["is_sla_breached"]),
    }


def fit_logistic_models(orders: pd.DataFrame) -> dict[str, Any]:
    customer_experience_frame = build_model_frame(orders, ["is_severe_detractor"])
    first_orders = orders.loc[orders["customer_order_seq"] == 1]
    first_order_frame = build_model_frame(first_orders, ["is_severe_detractor", "is_repeat_buyer"])
    fixed_horizon_frame = build_model_frame(
        first_orders, ["is_severe_detractor", "is_repeat_within_180d_after_delivery"]
    )
    return {
        "model_1_severe_detractor": fit_logit(
            customer_experience_frame,
            "is_severe_detractor",
            MODEL_1_FEATURES,
            "is_sla_breached",
            "Customer experience: P(severe detractor review) on all reviewed delivered orders",
        ),
        "model_2_repeat_buyer": fit_logit(
            first_order_frame,
            "is_repeat_buyer",
            MODEL_1_FEATURES,
            "is_sla_breached",
            "Retention: P(customer ever places >= 2 delivered orders) given first-order SLA breach",
        ),
        "model_2b_repeat_buyer_detractor_exposure": fit_logit(
            first_order_frame,
            "is_repeat_buyer",
            MODEL_2B_FEATURES,
            "is_severe_detractor",
            "Retention sensitivity: exposure = first-order severe detractor review instead of SLA breach",
        ),
        "model_2c_repeat_within_180d_after_delivery": fit_logit(
            fixed_horizon_frame,
            "is_repeat_within_180d_after_delivery",
            MODEL_1_FEATURES,
            "is_sla_breached",
            "Retention timing-clean sensitivity: new order within 180 days AFTER first delivery "
            "(first orders with a full 180-day follow-up window only)",
        ),
        "model_1_fixed_effects_robustness": fit_fixed_effects_robustness(orders),
    }


def trapezoid_integral(y_values: np.ndarray, x_values: np.ndarray) -> float:
    integrate = getattr(np, "trapezoid", None) or np.trapz
    return float(integrate(y_values, x_values))


def lorenz_curve(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ascending = np.sort(np.asarray(values, dtype=float))
    cumulative_value_share = np.concatenate([[0.0], np.cumsum(ascending) / ascending.sum()])
    cumulative_population_share = np.arange(len(ascending) + 1, dtype=float) / len(ascending)
    return cumulative_population_share, cumulative_value_share


def lorenz_gini(values: np.ndarray) -> float:
    cumulative_population_share, cumulative_value_share = lorenz_curve(values)
    return 1.0 - 2.0 * trapezoid_integral(cumulative_value_share, cumulative_population_share)


def bootstrap_gini_interval(values: np.ndarray) -> tuple[float, float]:
    resamples = np.random.choice(values, size=(GINI_BOOTSTRAP_RESAMPLES, len(values)), replace=True)
    bootstrap_ginis = np.array([lorenz_gini(resample) for resample in resamples])
    return float(np.percentile(bootstrap_ginis, 2.5)), float(np.percentile(bootstrap_ginis, 97.5))


def seller_share_for_gmv_threshold(sellers: pd.DataFrame, gmv_share_threshold: float) -> dict[str, float | int]:
    seller_rank = int(sellers.loc[sellers["cumulative_gmv_share"] >= gmv_share_threshold - 1e-12, "seller_rank"].min())
    return {"sellers": seller_rank, "seller_share_pct": 100.0 * seller_rank / len(sellers)}


def summarise_pareto_tiers(sellers: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    platform_gmv = float(sellers["seller_gmv"].sum())
    tier_rows: list[dict[str, Any]] = []
    breach_contingency: list[list[int]] = []
    for tier in PARETO_TIER_ORDER:
        tier_sellers = sellers.loc[sellers["pareto_tier"] == tier]
        tier_orders = int(tier_sellers["total_orders"].sum())
        tier_breaches = int(tier_sellers["breached_orders"].sum())
        tier_reviewed = int(tier_sellers["reviewed_orders"].sum())
        weighted_review_total = float((tier_sellers["mean_review_score"].fillna(0.0) * tier_sellers["reviewed_orders"]).sum())
        tier_gmv = float(tier_sellers["seller_gmv"].sum())
        tier_rows.append(
            {
                "pareto_tier": tier,
                "sellers": int(len(tier_sellers)),
                "gmv_brl": tier_gmv,
                "gmv_share_pct": 100.0 * tier_gmv / platform_gmv,
                "seller_orders": tier_orders,
                "orders_per_seller": tier_orders / len(tier_sellers),
                "mean_seller_gmv_brl": float(tier_sellers["seller_gmv"].mean()),
                "median_seller_gmv_brl": float(tier_sellers["seller_gmv"].median()),
                "gmv_per_seller_order_brl": tier_gmv / tier_orders,
                "sla_breach": proportion_summary(tier_breaches, tier_orders),
                "order_weighted_mean_review_score": weighted_review_total / tier_reviewed if tier_reviewed else None,
                "mean_of_seller_breach_rates_pct": 100.0 * float(tier_sellers["sla_breach_rate"].mean()),
                "order_weighted_mean_delivery_days": float(
                    (tier_sellers["mean_delivery_days"] * tier_sellers["total_orders"]).sum() / tier_orders
                ),
            }
        )
        breach_contingency.append([tier_breaches, tier_orders - tier_breaches])
    chi2_statistic, p_value, degrees_of_freedom, _ = stats.chi2_contingency(np.array(breach_contingency))
    return tier_rows, {
        "chi2_statistic": float(chi2_statistic),
        "degrees_of_freedom": int(degrees_of_freedom),
        "p_value": float(p_value),
    }


def seller_quality_correlation(sellers: pd.DataFrame) -> dict[str, float | int]:
    established = sellers.loc[
        (sellers["total_orders"] >= SELLER_MIN_ORDERS_FOR_CORRELATION) & sellers["mean_review_score"].notna()
    ]
    correlation = stats.spearmanr(established["sla_breach_rate"], established["mean_review_score"])
    return {
        "min_orders_per_seller": SELLER_MIN_ORDERS_FOR_CORRELATION,
        "sellers": int(len(established)),
        "spearman_rho_breach_rate_vs_mean_review": float(correlation.statistic),
        "p_value": float(correlation.pvalue),
    }


def analyse_seller_concentration(sellers: pd.DataFrame) -> dict[str, Any]:
    seller_gmv = sellers["seller_gmv"].to_numpy(dtype=float)
    gini_ci_low, gini_ci_high = bootstrap_gini_interval(seller_gmv)
    tier_rows, tier_breach_test = summarise_pareto_tiers(sellers)
    return {
        "sellers_with_delivered_orders": int(len(sellers)),
        "platform_seller_gmv_brl": float(seller_gmv.sum()),
        "gini_coefficient": lorenz_gini(seller_gmv),
        "gini_bootstrap_ci_low": gini_ci_low,
        "gini_bootstrap_ci_high": gini_ci_high,
        "gini_bootstrap_resamples": GINI_BOOTSTRAP_RESAMPLES,
        "gini_method": "1 - 2 * trapezoid(cum_gmv_share, cum_seller_share), sellers ascending by GMV, [0,0] prepended",
        "sellers_for_50pct_gmv": seller_share_for_gmv_threshold(sellers, 0.50),
        "sellers_for_80pct_gmv": seller_share_for_gmv_threshold(sellers, 0.80),
        "top_seller_gmv_share_pct": 100.0 * float(seller_gmv.max() / seller_gmv.sum()),
        "pareto_tiers": tier_rows,
        "tier_sla_breach_independence_test": tier_breach_test,
        "seller_quality_correlation": seller_quality_correlation(sellers),
    }


def summarise_cohort_retention(cohorts: pd.DataFrame) -> dict[str, Any]:
    retained_periods = cohorts.loc[cohorts["period_number"] >= 1]
    pooled_by_period = [
        {
            "period_number": int(period),
            "cohorts_observed": int(len(period_rows)),
            "pooled_retention_pct": 100.0 * float(period_rows["active_buyers"].sum()) / float(period_rows["cohort_size"].sum()),
            "active_buyers": int(period_rows["active_buyers"].sum()),
        }
        for period, period_rows in retained_periods.groupby("period_number")
    ]
    peak_cell = retained_periods.loc[retained_periods["retention_rate_pct"].idxmax()]
    cohort_sizes = cohorts.loc[cohorts["period_number"] == 0, ["cohort_month", "cohort_size", "cohort_gmv"]]
    return {
        "cohort_window": "2017-01..2018-08 acquisition cohorts, activity 2017-01-01..2018-08-31, periods 0..11",
        "cohorts": int(len(cohort_sizes)),
        "cohort_buyers": int(cohort_sizes["cohort_size"].sum()),
        "smallest_cohort_size": int(cohort_sizes["cohort_size"].min()),
        "largest_cohort_size": int(cohort_sizes["cohort_size"].max()),
        "observable_cells_period_1_to_11": int(len(retained_periods)),
        "zero_retention_cells_period_1_to_11": int((retained_periods["active_buyers"] == 0).sum()),
        "mean_cell_retention_pct_period_1_to_11": float(retained_periods["retention_rate_pct"].mean()),
        "pooled_month_1_retention_pct": pooled_by_period[0]["pooled_retention_pct"] if pooled_by_period else None,
        "peak_cell": {
            "cohort_month": peak_cell["cohort_month"],
            "period_number": int(peak_cell["period_number"]),
            "retention_rate_pct": float(peak_cell["retention_rate_pct"]),
            "cohort_size": int(peak_cell["cohort_size"]),
        },
        "pooled_retention_by_period": pooled_by_period,
        "period_0_gmv_share_pct": 100.0 * float(cohort_sizes["cohort_gmv"].sum()) / float(cohorts["cohort_gmv"].sum()),
    }


def build_headline(metrics: dict[str, Any]) -> dict[str, Any]:
    breach_term = next(
        term for term in metrics["logistic_models"]["model_1_severe_detractor"]["terms"] if term["term"] == "is_sla_breached"
    )
    pareto_80 = metrics["seller_concentration"]["sellers_for_80pct_gmv"]["seller_share_pct"]
    p_value_text = "p < 0.0001" if breach_term["p_value"] < 1e-4 else f"p = {breach_term['p_value']:.4f}"
    sentence = (
        "Missing the promised delivery SLA date multiplies the odds of a severe detractor review (1–2 stars) by "
        f"{breach_term['odds_ratio']:.1f}× (adjusted OR, 95% CI: [{breach_term['or_ci_low']:.2f}, "
        f"{breach_term['or_ci_high']:.2f}], {p_value_text}), while the top {pareto_80:.1f}% of sellers generate "
        "80% of platform GMV."
    )
    return {
        "sentence": sentence,
        "model_1_breach_odds_ratio": breach_term["odds_ratio"],
        "model_1_breach_or_ci_low": breach_term["or_ci_low"],
        "model_1_breach_or_ci_high": breach_term["or_ci_high"],
        "model_1_breach_p_value": breach_term["p_value"],
        "top_seller_share_for_80pct_gmv_pct": pareto_80,
    }


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def write_metrics(metrics: dict[str, Any], metrics_path: Path = METRICS_PATH) -> Path:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(to_json_safe(metrics), indent=2, ensure_ascii=False), encoding="utf-8")
    return metrics_path


def load_metrics(metrics_path: Path = METRICS_PATH) -> dict[str, Any]:
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def run_analysis(pipeline_reports: dict[str, Any] | None = None) -> dict[str, Any]:
    np.random.seed(RANDOM_SEED)
    with connect_read_only() as connection:
        orders = load_orders(connection)
        sellers = connection.execute("SELECT * FROM mart_seller_pareto ORDER BY seller_rank").df()
        cohorts = connection.execute("SELECT * FROM mart_cohort_retention ORDER BY cohort_month, period_number").df()
    metrics: dict[str, Any] = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "random_seed": RANDOM_SEED,
            "data_source": SOURCE_BASE_URL,
            "confidence_level": 1.0 - ALPHA,
            "on_time_baseline_delay_days_for_api": ON_TIME_BASELINE_DELAY_DAYS,
            "package_versions": package_versions(),
        },
        "data_integrity": pipeline_reports or {},
        "platform_kpis": compute_platform_kpis(orders),
        "two_sample_tests": {
            "review_score": compare_review_scores(orders),
            "severe_detractor": compare_severe_detractor_rates(orders),
            "repeat_purchase": compare_repeat_purchase(orders),
        },
        "sla_threshold_discontinuity": estimate_sla_threshold_discontinuity(orders),
        "sla_delay_day_profile": build_sla_delay_day_profile(orders),
        "sla_bucket_profile": build_sla_bucket_profile(orders),
        "logistic_models": fit_logistic_models(orders),
        "seller_concentration": analyse_seller_concentration(sellers),
        "cohort_retention": summarise_cohort_retention(cohorts),
    }
    metrics["headline"] = build_headline(metrics)
    safe_metrics = to_json_safe(metrics)
    write_metrics(safe_metrics)
    return safe_metrics
