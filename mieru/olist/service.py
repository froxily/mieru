from typing import Any

import numpy as np
import pandas as pd

from mieru.olist.categories import CATEGORY_NAMES_EN
from mieru.olist.metrics import OLIST_CURRENCY, explain_olist_metric
from mieru.olist.warehouse import OlistWarehouse
from src.analysis import lorenz_curve

LORENZ_POINTS: int = 300
TOP_CATEGORY_COUNT: int = 15
TOP_SELLER_COUNT: int = 15
RESEARCH_FIGURES: dict[str, str] = {
    "01_cohort_retention_heatmap.png": "Monthly cohort retention heatmap",
    "02_sla_breach_penalty_curve.png": "SLA breach penalty curve",
    "03_seller_pareto_lorenz.png": "Seller GMV Pareto / Lorenz curve",
    "04_logit_odds_ratios_forest.png": "Adjusted odds-ratio forest plot",
}
BRAZIL_STATE_NAMES: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}
DATASET_ATTRIBUTION: str = (
    "Olist Brazilian E-Commerce Public Dataset (github.com/olist/work-at-olist-data). Real, anonymised marketplace data; "
    "see the source repository for licence terms."
)


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        return as_float if np.isfinite(as_float) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{column: clean_value(value) for column, value in row.items()} for row in frame.to_dict(orient="records")]


def prettify_category(raw_category: str) -> str:
    if not raw_category:
        return raw_category
    return CATEGORY_NAMES_EN.get(raw_category, raw_category.replace("_", " ").strip().capitalize())


def kpi(warehouse: OlistWarehouse, metric_id: str, context: str | None = None) -> dict[str, Any]:
    explanation = explain_olist_metric(warehouse, metric_id)
    return {
        "metric_id": metric_id,
        "label": explanation.definition.label,
        "value": explanation.value,
        "unit": explanation.definition.unit,
        "currency": explanation.currency,
        "status": explanation.status,
        "context": context,
    }


def monthly_records(warehouse: OlistWarehouse) -> list[dict[str, Any]]:
    frame = warehouse.query_frame(
        """
        SELECT strftime(purchase_month, '%Y-%m') AS month, delivered_orders, active_customers, first_time_customers,
               gmv, product_sales, freight, average_order_value, sla_breach_rate, mean_review_score,
               severe_detractor_rate, median_delivery_days, median_promised_days, is_partial, coverage_note
        FROM mart_olist_monthly ORDER BY purchase_month
        """
    )
    return frame_records(frame)


def build_overview(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    kpis = research["platform_kpis"]
    categories = warehouse.query_frame(
        "SELECT category, orders, items_sold, gmv, gmv_share, freight_share, mean_review_score, sla_breach_rate, gmv_rank "
        "FROM mart_olist_category ORDER BY gmv_rank"
    )
    categories["display_name"] = categories["category"].map(prettify_category)
    top_categories = categories.head(TOP_CATEGORY_COUNT)
    remainder = categories.iloc[TOP_CATEGORY_COUNT:]
    states = warehouse.query_frame(
        "SELECT customer_state, delivered_orders, customers, gmv, gmv_share, average_order_value, sla_breach_rate, "
        "mean_review_score, median_delivery_days FROM mart_olist_state ORDER BY gmv DESC"
    )
    states["state_name"] = states["customer_state"].map(BRAZIL_STATE_NAMES).fillna(states["customer_state"])
    payments = warehouse.query_frame(
        "SELECT payment_type, payment_records, orders_using_type, payment_value, payment_value_share, mean_installments "
        "FROM mart_olist_payments ORDER BY payment_value DESC"
    )
    top_category = top_categories.iloc[0]
    top_state = states.iloc[0]
    complete_months = [row for row in monthly_records(warehouse) if not row["is_partial"]]
    peak_month = max(complete_months, key=lambda row: row["gmv"])
    return {
        "dataset": {
            "name": "Olist Brazilian E-Commerce",
            "currency": OLIST_CURRENCY,
            "purchase_window_start": kpis["purchase_window_start"],
            "purchase_window_end": kpis["purchase_window_end"],
            "attribution": DATASET_ATTRIBUTION,
        },
        "kpis": [
            kpi(warehouse, "olist.gmv", "Price + freight, delivered orders"),
            kpi(warehouse, "olist.delivered_orders"),
            kpi(warehouse, "olist.aov"),
            kpi(warehouse, "olist.customers", "Resolved on customer_unique_id"),
            kpi(warehouse, "olist.mean_review_score", "1–5 stars, reviewed orders"),
            kpi(warehouse, "olist.sla_breach_rate", "Delivered after the promised date"),
            kpi(warehouse, "olist.repeat_purchase_rate", "Customers with ≥ 2 delivered orders"),
            kpi(warehouse, "olist.active_sellers"),
        ],
        "monthly": monthly_records(warehouse),
        "categories": {
            "top": frame_records(top_categories),
            "remainder": {
                "categories": int(len(remainder)),
                "gmv": float(remainder["gmv"].sum()),
                "gmv_share": float(remainder["gmv_share"].sum()),
                "orders_note": "Order counts are not additive across categories (an order can contain several categories).",
            },
            "total_categories": int(len(categories)),
        },
        "states": frame_records(states),
        "payments": frame_records(payments),
        "highlights": [
            {
                "title": "Largest category",
                "text": f"{prettify_category(top_category['category'])} contributes {top_category['gmv_share'] * 100:.1f}% of GMV.",
                "metric_id": "olist.gmv",
            },
            {
                "title": "Geographic concentration",
                "text": f"{BRAZIL_STATE_NAMES.get(top_state['customer_state'], top_state['customer_state'])} accounts for "
                f"{top_state['gmv_share'] * 100:.1f}% of GMV across {int(top_state['delivered_orders']):,} delivered orders.",
                "metric_id": "olist.gmv",
            },
            {
                "title": "Peak complete month",
                "text": f"{peak_month['month']} was the highest-GMV complete month "
                f"(R$ {peak_month['gmv']:,.0f} from {int(peak_month['delivered_orders']):,} orders).",
                "metric_id": "olist.gmv",
            },
            {
                "title": "Delivery promise",
                "text": f"The median order arrives {abs(kpis['median_sla_delay_days']):.0f} days before its promised date, "
                f"yet {kpis['sla_breach_rate_pct']:.1f}% still arrive late.",
                "metric_id": "olist.sla_breach_rate",
            },
        ],
    }


def build_delivery(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    tests = research["two_sample_tests"]
    model_one = research["logistic_models"]["model_1_severe_detractor"]
    fixed_effects = research["logistic_models"]["model_1_fixed_effects_robustness"]
    states = warehouse.query_frame(
        "SELECT customer_state, delivered_orders, sla_breach_rate, mean_review_score, severe_detractor_rate, "
        "median_delivery_days, median_promised_days, median_distance_km FROM mart_olist_state ORDER BY sla_breach_rate DESC"
    )
    states["state_name"] = states["customer_state"].map(BRAZIL_STATE_NAMES).fillna(states["customer_state"])
    breach_term = next(term for term in model_one["terms"] if term["term"] == "is_sla_breached")
    return {
        "kpis": [
            kpi(warehouse, "olist.sla_breach_rate"),
            kpi(warehouse, "olist.median_delivery_days", "Purchase → delivered to customer"),
            kpi(warehouse, "olist.mean_review_score"),
            kpi(warehouse, "olist.severe_detractor_rate", "1–2 star reviews"),
        ],
        "review_gap": {
            "on_time_mean": tests["review_score"]["on_time"]["mean"],
            "breached_mean": tests["review_score"]["sla_breached"]["mean"],
            "difference": tests["review_score"]["mean_difference_breached_minus_on_time"],
            "difference_ci": [tests["review_score"]["mean_difference_ci_low"], tests["review_score"]["mean_difference_ci_high"]],
            "welch_p_display": tests["review_score"]["welch_p_value_display"],
            "on_time_detractor_rate_pct": tests["severe_detractor"]["on_time"]["rate_pct"],
            "breached_detractor_rate_pct": tests["severe_detractor"]["sla_breached"]["rate_pct"],
            "relative_risk": tests["severe_detractor"]["relative_risk"],
            "relative_risk_ci": [tests["severe_detractor"]["relative_risk_ci_low"], tests["severe_detractor"]["relative_risk_ci_high"]],
        },
        "adjusted_model": {
            "odds_ratio": breach_term["odds_ratio"],
            "odds_ratio_ci": [breach_term["or_ci_low"], breach_term["or_ci_high"]],
            "p_value": breach_term["p_value"],
            "average_marginal_effect_pp": model_one["exposure_effect"]["average_marginal_effect_pp"],
            "excess_detractors": model_one["exposure_effect"]["excess_events_among_exposed"],
            "excess_share_pct": model_one["exposure_effect"]["excess_events_share_of_all_events_pct"],
            "fixed_effects_odds_ratio": fixed_effects["is_sla_breached_odds_ratio"],
            "fixed_effects_ci": [fixed_effects["is_sla_breached_or_ci_low"], fixed_effects["is_sla_breached_or_ci_high"]],
            "n_obs": model_one["n_obs"],
            "caveat": "Adjusted association from observational data (logistic regression, HC0 robust SEs) — not a randomised causal estimate.",
        },
        "threshold": research["sla_threshold_discontinuity"],
        "day_profile": research["sla_delay_day_profile"],
        "bucket_profile": research["sla_bucket_profile"],
        "monthly": [
            {key: row[key] for key in ("month", "delivered_orders", "sla_breach_rate", "mean_review_score", "median_delivery_days", "median_promised_days", "is_partial", "coverage_note")}
            for row in monthly_records(warehouse)
        ],
        "states": frame_records(states),
        "simulator": {
            "endpoint": "/api/olist/research/sla-simulator",
            "baseline_delay_days": research["metadata"]["on_time_baseline_delay_days_for_api"],
            "note": "Model 1 encodes delay as a binary breach flag, so predictions depend only on whether delay_days > 0.",
        },
    }


def build_customers(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    cohorts = warehouse.query_frame(
        "SELECT strftime(cohort_month, '%Y-%m') AS cohort_month, period_number, cohort_size, active_buyers, retention_rate_pct, cohort_gmv "
        "FROM mart_cohort_retention ORDER BY cohort_month, period_number"
    )
    cohort_months = list(dict.fromkeys(cohorts["cohort_month"]))
    sizes = cohorts.loc[cohorts["period_number"] == 0].set_index("cohort_month")["cohort_size"].to_dict()
    matrix: list[list[float | None]] = []
    for month in cohort_months:
        month_rows = cohorts.loc[cohorts["cohort_month"] == month].set_index("period_number")["retention_rate_pct"]
        matrix.append([clean_value(month_rows.get(period)) if period in month_rows.index else None for period in range(0, 12)])
    models = research["logistic_models"]
    repeat_tests = research["two_sample_tests"]["repeat_purchase"]

    def model_summary(model_key: str) -> dict[str, Any]:
        model = models[model_key]
        exposure_term = next(term for term in model["terms"] if term["term"] == model["exposure"])
        return {
            "description": model["description"],
            "exposure": model["exposure"],
            "n_obs": model["n_obs"],
            "n_events": model["n_events"],
            "odds_ratio": exposure_term["odds_ratio"],
            "odds_ratio_ci": [exposure_term["or_ci_low"], exposure_term["or_ci_high"]],
            "p_value": exposure_term["p_value"],
            "significant_at_5pct": exposure_term["p_value"] < 0.05,
        }

    return {
        "kpis": [
            kpi(warehouse, "olist.customers"),
            kpi(warehouse, "olist.repeat_purchase_rate"),
        ],
        "platform": {
            "single_purchase_share_pct": research["platform_kpis"]["single_purchase_customer_share_pct"],
            "repeat_customers": research["platform_kpis"]["repeat_customers"],
            "same_day_only_repeaters": research["platform_kpis"]["repeat_customers_with_all_orders_same_day"],
            "repeat_within_180d_pct": research["platform_kpis"]["customer_repeat_within_180d_of_first_delivery_rate_pct"],
        },
        "cohorts": {
            "months": cohort_months,
            "sizes": [int(sizes[month]) for month in cohort_months],
            "periods": list(range(0, 12)),
            "retention_pct": matrix,
            "summary": research["cohort_retention"],
        },
        "repeat_by_bucket": repeat_tests["by_sla_delay_bucket"],
        "models": {
            "model_2_repeat_buyer": model_summary("model_2_repeat_buyer"),
            "model_2b_detractor_exposure": model_summary("model_2b_repeat_buyer_detractor_exposure"),
            "model_2c_fixed_horizon": model_summary("model_2c_repeat_within_180d_after_delivery"),
        },
        "caveat": (
            "~97% of customers buy once, so retention is structurally near zero. The naive repeat model is partly a right-censoring "
            "artifact (older orders had more follow-up time); the fixed 180-day horizon (Model 2c) is the defensible estimate and is "
            "not statistically significant."
        ),
    }


def build_sellers(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    concentration = research["seller_concentration"]
    sellers = warehouse.query_frame(
        "SELECT seller_id, total_orders, total_items, seller_gmv, sla_breach_rate, mean_review_score, mean_delivery_days, "
        "seller_rank, cumulative_gmv_share, pareto_tier FROM mart_seller_pareto ORDER BY seller_rank"
    )
    population_share, value_share = lorenz_curve(sellers["seller_gmv"].to_numpy(dtype=float))
    sample_index = np.unique(np.round(np.linspace(0, len(population_share) - 1, LORENZ_POINTS)).astype(int))
    top_sellers = sellers.head(TOP_SELLER_COUNT).copy()
    top_sellers["seller_label"] = "Seller " + top_sellers["seller_id"].str[:8]
    size_bins = [0, 1_000, 5_000, 20_000, 100_000, float("inf")]
    size_labels = ["< R$1k", "R$1k–5k", "R$5k–20k", "R$20k–100k", "≥ R$100k"]
    size_distribution = (
        pd.cut(sellers["seller_gmv"], bins=size_bins, labels=size_labels, right=False)
        .value_counts(sort=False)
        .rename_axis("band")
        .reset_index(name="sellers")
    )
    size_distribution["band"] = size_distribution["band"].astype(str)
    return {
        "kpis": [
            kpi(warehouse, "olist.active_sellers"),
            kpi(warehouse, "olist.seller_gmv_gini", "0 = equal, 1 = fully concentrated"),
            kpi(warehouse, "olist.seller_share_for_80pct_gmv", "Share of sellers producing 80% of GMV"),
        ],
        "gini": {
            "value": concentration["gini_coefficient"],
            "ci": [concentration["gini_bootstrap_ci_low"], concentration["gini_bootstrap_ci_high"]],
            "method": concentration["gini_method"],
        },
        "pareto": {
            "sellers_for_50pct": concentration["sellers_for_50pct_gmv"],
            "sellers_for_80pct": concentration["sellers_for_80pct_gmv"],
        },
        "lorenz": {
            "seller_share": [float(population_share[index]) for index in sample_index],
            "gmv_share": [float(value_share[index]) for index in sample_index],
        },
        "tiers": concentration["pareto_tiers"],
        "tier_breach_test": concentration["tier_sla_breach_independence_test"],
        "quality_correlation": concentration["seller_quality_correlation"],
        "top_sellers": frame_records(
            top_sellers[["seller_label", "seller_rank", "total_orders", "seller_gmv", "sla_breach_rate", "mean_review_score", "cumulative_gmv_share", "pareto_tier"]]
        ),
        "size_distribution": frame_records(size_distribution),
    }


def build_research(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    models = research["logistic_models"]
    return {
        "headline": research["headline"],
        "metadata": research["metadata"],
        "platform_kpis": research["platform_kpis"],
        "two_sample_tests": {
            "review_score": research["two_sample_tests"]["review_score"],
            "severe_detractor": research["two_sample_tests"]["severe_detractor"],
        },
        "threshold": research["sla_threshold_discontinuity"],
        "models": {
            key: {
                "description": value.get("description"),
                "n_obs": value.get("n_obs"),
                "n_events": value.get("n_events"),
                "pseudo_r2_mcfadden": value.get("pseudo_r2_mcfadden"),
                "roc_auc": value.get("roc_auc"),
                "converged": value.get("converged"),
                "terms": value.get("terms"),
                "exposure": value.get("exposure"),
                "odds_ratio": value.get("is_sla_breached_odds_ratio"),
                "odds_ratio_ci": [value.get("is_sla_breached_or_ci_low"), value.get("is_sla_breached_or_ci_high")]
                if "is_sla_breached_or_ci_low" in value
                else None,
            }
            for key, value in models.items()
        },
        "seller_concentration": {
            key: research["seller_concentration"][key]
            for key in ("gini_coefficient", "gini_bootstrap_ci_low", "gini_bootstrap_ci_high", "sellers_for_50pct_gmv", "sellers_for_80pct_gmv")
        },
        "cohort_retention": research["cohort_retention"],
        "figures": [
            {"file_name": file_name, "title": title, "url": f"/api/olist/figures/{file_name}"}
            for file_name, title in RESEARCH_FIGURES.items()
            if warehouse.figure_path(file_name) is not None
        ],
        "caveats": [
            "Observational data: odds ratios are adjusted associations, supported by a dose-response and a sharp Day 0 → +1 jump with a null placebo step, "
            "but exposed to unobserved confounders (carrier, category, seller quality).",
            "Retention is near zero (~97% single-purchase); the naive repeat model is biased by follow-up time, and the fixed-horizon estimate is not significant.",
            "GMV includes freight and is not Olist revenue; the dataset has no cost data, so profit is not computed.",
        ],
        "attribution": DATASET_ATTRIBUTION,
    }
