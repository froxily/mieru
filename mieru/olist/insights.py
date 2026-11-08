from typing import Any

from mieru.insights.cards import Evidence, InsightCard
from mieru.olist.metrics import OLIST_CURRENCY
from mieru.olist.service import BRAZIL_STATE_NAMES
from mieru.olist.warehouse import OlistWarehouse

MIN_STATE_ORDERS: int = 500
OBSERVATIONAL_CAVEAT: str = "Observational data: this is an adjusted association, not a randomised causal estimate."


def build_olist_insights(warehouse: OlistWarehouse) -> dict[str, Any]:
    research = warehouse.research_metrics()
    tests = research["two_sample_tests"]
    model_one = research["logistic_models"]["model_1_severe_detractor"]
    breach_term = next(term for term in model_one["terms"] if term["term"] == "is_sla_breached")
    fixed_effects = research["logistic_models"]["model_1_fixed_effects_robustness"]
    threshold = research["sla_threshold_discontinuity"]
    concentration = research["seller_concentration"]
    tiers = {tier["pareto_tier"]: tier for tier in concentration["pareto_tiers"]}
    kpis = research["platform_kpis"]
    model_2c = research["logistic_models"]["model_2c_repeat_within_180d_after_delivery"]
    model_2c_term = next(term for term in model_2c["terms"] if term["term"] == "is_sla_breached")
    states = warehouse.query_frame(
        "SELECT customer_state, delivered_orders, gmv_share, sla_breach_rate, median_delivery_days FROM mart_olist_state ORDER BY gmv DESC"
    )
    large_states = states[states["delivered_orders"] >= MIN_STATE_ORDERS]
    worst_state = large_states.sort_values("sla_breach_rate", ascending=False).iloc[0]
    top_state = states.iloc[0]
    payments = warehouse.query_frame("SELECT payment_type, payment_value_share, mean_installments FROM mart_olist_payments ORDER BY payment_value DESC")
    card_payment = payments.iloc[0]
    cards = [
        InsightCard(
            insight_id="sla_breach_detractors",
            kind="risk",
            confidence="high",
            finding=f"Late deliveries turn {tests['severe_detractor']['sla_breached']['rate_pct']:.0f}% of reviews into 1–2 stars, versus "
            f"{tests['severe_detractor']['on_time']['rate_pct']:.0f}% when the promise is kept.",
            evidence=(
                Evidence("Adjusted odds ratio (SLA breach → 1–2★)", breach_term["odds_ratio"], "index"),
                Evidence("Odds ratio with state + month fixed effects", fixed_effects["is_sla_breached_odds_ratio"], "index"),
                Evidence("Share of all 1–2★ reviews attributable to breaches (if causal)", model_one["exposure_effect"]["excess_events_share_of_all_events_pct"] / 100, "share"),
                Evidence("SLA breach rate", kpis["sla_breach_rate_pct"] / 100, "ratio", metric_id="olist.sla_breach_rate"),
            ),
            interpretation="Keeping the delivery promise is the single largest lever on public ratings in this marketplace.",
            action="Trigger proactive delay messages and service-recovery offers before the promised date for orders predicted to be late; "
            "set the promised date from a high quantile of route-level lead time.",
            limitations=(OBSERVATIONAL_CAVEAT, "Unobserved factors (carrier, product category, seller quality) may contribute."),
            gates=(f"n = {model_one['n_obs']:,} reviewed orders", "HC0 robust standard errors"),
        ),
        InsightCard(
            insight_id="promise_cliff",
            kind="info",
            confidence="high",
            finding=f"Reviews fall off a cliff one day after the promised date: 1–2★ rate {threshold['day_0_severe_detractor']['rate_pct']:.1f}% on Day 0 "
            f"vs {threshold['day_plus_1_severe_detractor']['rate_pct']:.1f}% on Day +1.",
            evidence=(
                Evidence("Jump at the promise (Day 0 → +1), percentage points", threshold["threshold_jump_day0_to_plus1"]["absolute_difference_pp"], "index"),
                Evidence("Placebo step (Day −1 → 0), percentage points", threshold["placebo_jump_minus1_to_day0"]["absolute_difference_pp"], "index"),
                Evidence("Placebo p-value", threshold["placebo_jump_minus1_to_day0"]["chi2_p_value"], "index"),
            ),
            interpretation="Customers grade against the promise, not absolute speed; arriving very early earns little extra.",
            action="Do not shorten promised dates to look faster: optimise the probability of on-time delivery instead.",
            limitations=("Local comparison of adjacent days; still observational.",),
            gates=(f"Day 0 n = {threshold['day_0_severe_detractor']['n']:,} · Day +1 n = {threshold['day_plus_1_severe_detractor']['n']:,}",),
        ),
        InsightCard(
            insight_id="seller_concentration",
            kind="risk",
            confidence="high",
            finding=f"The top {concentration['sellers_for_80pct_gmv']['seller_share_pct']:.1f}% of sellers generate 80% of GMV, and the top 10% breach the "
            f"delivery promise {tiers['Top 10% Sellers']['sla_breach']['rate_pct']:.1f}% of the time vs {tiers['Bottom 50% Long-Tail']['sla_breach']['rate_pct']:.1f}% for the long tail.",
            evidence=(
                Evidence("Seller GMV Gini", concentration["gini_coefficient"], "index", metric_id="olist.seller_gmv_gini"),
                Evidence("GMV share of top-10% sellers", tiers["Top 10% Sellers"]["gmv_share_pct"] / 100, "share"),
                Evidence("Sellers in the top tier", float(tiers["Top 10% Sellers"]["sellers"]), "count"),
            ),
            interpretation="Platform GMV depends on a few hundred sellers whose fulfilment reliability has not improved with scale.",
            action="Run a seller-level SLA programme for the ~300 top-tier sellers: it covers about two-thirds of GMV.",
            limitations=("Tier breach rates are seller-order weighted; multi-seller orders count once per seller.",),
            gates=(f"tier χ² p = {concentration['tier_sla_breach_independence_test']['p_value']:.4f}",),
        ),
        InsightCard(
            insight_id="retention_structural",
            kind="info",
            confidence="high",
            finding=f"{kpis['single_purchase_customer_share_pct']:.0f}% of customers buy only once; a late first delivery's effect on repeat purchase is small "
            f"and not statistically significant once follow-up time is fixed (OR {model_2c_term['odds_ratio']:.2f}, p = {model_2c_term['p_value']:.2f}).",
            evidence=(
                Evidence("Repeat-purchase rate", kpis["customer_repeat_purchase_rate_pct"] / 100, "ratio", metric_id="olist.repeat_purchase_rate"),
                Evidence("Repeat within 180 days of first delivery", kpis["customer_repeat_within_180d_of_first_delivery_rate_pct"] / 100, "ratio"),
            ),
            interpretation="Retention is a separate problem from logistics: fixing deliveries lifts ratings but will not by itself create repeat buyers.",
            action="Address retention with CRM, loyalty mechanics or category expansion, and measure it with fixed follow-up windows.",
            limitations=("Naive repeat rates are biased by follow-up time (right-censoring); the fixed-horizon model is the defensible estimate.",),
            gates=(f"n = {model_2c['n_obs']:,} first orders with 180 days of follow-up",),
        ),
        InsightCard(
            insight_id="state_breach_hotspot",
            kind="risk",
            confidence="high",
            finding=f"{BRAZIL_STATE_NAMES.get(worst_state['customer_state'], worst_state['customer_state'])} has the highest SLA breach rate among large states "
            f"({float(worst_state['sla_breach_rate']):.1%}), while {BRAZIL_STATE_NAMES.get(top_state['customer_state'], top_state['customer_state'])} "
            f"alone is {float(top_state['gmv_share']):.0%} of GMV.",
            evidence=(
                Evidence(f"SLA breach rate · {worst_state['customer_state']}", float(worst_state["sla_breach_rate"]), "ratio"),
                Evidence(f"Median delivery days · {worst_state['customer_state']}", float(worst_state["median_delivery_days"]), "days"),
                Evidence("Platform SLA breach rate", kpis["sla_breach_rate_pct"] / 100, "ratio", metric_id="olist.sla_breach_rate"),
            ),
            interpretation="Delivery risk is regional; long-haul routes miss promises far more often.",
            action="Pad promises (or add carriers) on the worst routes first; that is where breaches, and therefore 1–2★ reviews, concentrate.",
            limitations=(f"States with fewer than {MIN_STATE_ORDERS} delivered orders are excluded from the comparison.",),
            gates=(f"≥ {MIN_STATE_ORDERS} delivered orders per state",),
        ),
        InsightCard(
            insight_id="payment_mix",
            kind="info",
            confidence="high",
            finding=f"{str(card_payment['payment_type']).replace('_', ' ').capitalize()} carries {float(card_payment['payment_value_share']):.0%} of payment value, "
            f"with an average of {float(card_payment['mean_installments']):.1f} instalments.",
            evidence=(Evidence("Payment value share", float(card_payment["payment_value_share"]), "share", metric_id="olist.payment_value"),),
            interpretation="Instalment credit-card payments dominate: financing terms are part of the purchase decision.",
            action="Treat instalment availability as a conversion lever (e.g. highlight interest-free instalments on high-value items).",
            limitations=("Payment value is a different measure from GMV (instalment interest, vouchers).",),
            gates=("All payment records of delivered orders",),
        ),
    ]
    return {
        "cards": [card.to_dict() for card in cards],
        "skipped": [],
        "rules_evaluated": len(cards),
        "method": "Cards are generated from the frozen research pipeline outputs and the DuckDB dashboard marts; numbers are recomputed whenever the warehouse is rebuilt.",
        "currency": OLIST_CURRENCY,
    }
