import type { MetricUnit } from "../lib/format";

export interface Kpi {
  metric_id: string;
  label: string;
  value: number | null;
  unit: MetricUnit;
  currency: string | null;
  status: "ok" | "unavailable";
  context: string | null;
  unavailable_reason?: string | null;
}

export interface ProportionSummary {
  n: number;
  events: number;
  rate_pct: number | null;
  ci_low_pct: number | null;
  ci_high_pct: number | null;
}

export interface MeanSummary {
  n: number;
  mean: number | null;
  ci_low: number | null;
  ci_high: number | null;
}

export interface MonthlyRow {
  month: string;
  delivered_orders: number;
  active_customers?: number;
  first_time_customers?: number;
  gmv?: number;
  product_sales?: number;
  freight?: number;
  average_order_value?: number;
  sla_breach_rate: number;
  mean_review_score: number;
  severe_detractor_rate?: number;
  median_delivery_days: number;
  median_promised_days: number;
  is_partial: boolean;
  coverage_note: string | null;
}

export interface CategoryRow {
  category: string;
  display_name: string;
  orders: number;
  items_sold: number;
  gmv: number;
  gmv_share: number;
  freight_share: number;
  mean_review_score: number;
  sla_breach_rate: number;
  gmv_rank: number;
}

export interface StateRow {
  customer_state: string;
  state_name: string;
  delivered_orders: number;
  customers?: number;
  gmv?: number;
  gmv_share?: number;
  average_order_value?: number;
  sla_breach_rate: number;
  mean_review_score: number;
  severe_detractor_rate?: number;
  median_delivery_days: number;
  median_promised_days?: number;
  median_distance_km?: number;
}

export interface PaymentRow {
  payment_type: string;
  payment_records: number;
  orders_using_type: number;
  payment_value: number;
  payment_value_share: number;
  mean_installments: number;
}

export interface Highlight {
  title: string;
  text: string;
  metric_id: string;
}

export interface OlistOverview {
  dataset: {
    name: string;
    currency: string;
    purchase_window_start: string;
    purchase_window_end: string;
    attribution: string;
  };
  kpis: Kpi[];
  monthly: MonthlyRow[];
  categories: {
    top: CategoryRow[];
    remainder: { categories: number; gmv: number; gmv_share: number; orders_note: string };
    total_categories: number;
  };
  states: StateRow[];
  payments: PaymentRow[];
  highlights: Highlight[];
}

export interface DayProfileRow {
  sla_delay_days: number;
  orders: number;
  review_score: MeanSummary;
  severe_detractor: ProportionSummary;
}

export interface BucketProfileRow {
  sla_delay_bucket: string;
  orders: number;
  order_share_pct: number;
  review_score: MeanSummary;
  severe_detractor: ProportionSummary;
  five_star: ProportionSummary;
  mean_actual_delivery_days: number;
}

export interface TwoProportionTest {
  absolute_difference_pp: number;
  absolute_difference_ci_low_pp: number;
  absolute_difference_ci_high_pp: number;
  relative_risk: number | null;
  chi2_p_value: number;
  chi2_p_value_display: string;
}

export interface ThresholdDiscontinuity {
  design: string;
  day_minus_1_severe_detractor: ProportionSummary;
  day_0_severe_detractor: ProportionSummary;
  day_plus_1_severe_detractor: ProportionSummary;
  threshold_jump_day0_to_plus1: TwoProportionTest;
  placebo_jump_minus1_to_day0: TwoProportionTest;
  threshold_to_placebo_jump_ratio: number | null;
}

export interface OlistDelivery {
  kpis: Kpi[];
  review_gap: {
    on_time_mean: number;
    breached_mean: number;
    difference: number;
    difference_ci: [number, number];
    welch_p_display: string;
    on_time_detractor_rate_pct: number;
    breached_detractor_rate_pct: number;
    relative_risk: number;
    relative_risk_ci: [number, number];
  };
  adjusted_model: {
    odds_ratio: number;
    odds_ratio_ci: [number, number];
    p_value: number;
    average_marginal_effect_pp: number;
    excess_detractors: number;
    excess_share_pct: number;
    fixed_effects_odds_ratio: number;
    fixed_effects_ci: [number, number];
    n_obs: number;
    caveat: string;
  };
  threshold: ThresholdDiscontinuity;
  day_profile: DayProfileRow[];
  bucket_profile: BucketProfileRow[];
  monthly: MonthlyRow[];
  states: StateRow[];
  simulator: { endpoint: string; baseline_delay_days: number; note: string };
}

export interface ModelSummary {
  description: string;
  exposure: string;
  n_obs: number;
  n_events: number;
  odds_ratio: number;
  odds_ratio_ci: [number, number];
  p_value: number;
  significant_at_5pct: boolean;
}

export interface RepeatBucketRow {
  sla_delay_bucket: string;
  repeat_buyer: ProportionSummary;
  repeat_within_180d_after_first_delivery: ProportionSummary;
}

export interface OlistCustomers {
  kpis: Kpi[];
  platform: {
    single_purchase_share_pct: number;
    repeat_customers: number;
    same_day_only_repeaters: number;
    repeat_within_180d_pct: number;
  };
  cohorts: {
    months: string[];
    sizes: number[];
    periods: number[];
    retention_pct: (number | null)[][];
    summary: {
      pooled_month_1_retention_pct: number;
      mean_cell_retention_pct_period_1_to_11: number;
      peak_cell: { cohort_month: string; period_number: number; retention_rate_pct: number; cohort_size: number };
      pooled_retention_by_period: { period_number: number; pooled_retention_pct: number; active_buyers: number; cohorts_observed: number }[];
      cohort_buyers: number;
      cohorts: number;
    };
  };
  repeat_by_bucket: RepeatBucketRow[];
  models: {
    model_2_repeat_buyer: ModelSummary;
    model_2b_detractor_exposure: ModelSummary;
    model_2c_fixed_horizon: ModelSummary;
  };
  caveat: string;
}

export interface TierRow {
  pareto_tier: string;
  sellers: number;
  gmv_brl: number;
  gmv_share_pct: number;
  seller_orders: number;
  orders_per_seller: number;
  mean_seller_gmv_brl: number;
  median_seller_gmv_brl: number;
  gmv_per_seller_order_brl: number;
  sla_breach: ProportionSummary;
  order_weighted_mean_review_score: number;
}

export interface TopSellerRow {
  seller_label: string;
  seller_rank: number;
  total_orders: number;
  seller_gmv: number;
  sla_breach_rate: number;
  mean_review_score: number | null;
  cumulative_gmv_share: number;
  pareto_tier: string;
}

export interface OlistSellers {
  kpis: Kpi[];
  gini: { value: number; ci: [number, number]; method: string };
  pareto: {
    sellers_for_50pct: { sellers: number; seller_share_pct: number };
    sellers_for_80pct: { sellers: number; seller_share_pct: number };
  };
  lorenz: { seller_share: number[]; gmv_share: number[] };
  tiers: TierRow[];
  tier_breach_test: { chi2_statistic: number; degrees_of_freedom: number; p_value: number };
  quality_correlation: { sellers: number; spearman_rho_breach_rate_vs_mean_review: number; p_value: number; min_orders_per_seller: number };
  top_sellers: TopSellerRow[];
  size_distribution: { band: string; sellers: number }[];
}

export interface ModelTerm {
  term: string;
  coef_log_odds: number;
  std_err_hc0: number;
  z_stat: number;
  p_value: number;
  odds_ratio: number;
  or_ci_low: number;
  or_ci_high: number;
}

export interface ResearchModel {
  description: string | null;
  n_obs: number | null;
  n_events: number | null;
  pseudo_r2_mcfadden: number | null;
  roc_auc: number | null;
  converged: boolean | null;
  terms: ModelTerm[] | null;
  exposure: string | null;
  odds_ratio: number | null;
  odds_ratio_ci: [number, number] | null;
}

export interface OlistResearch {
  headline: { sentence: string };
  metadata: { generated_at_utc: string; random_seed: number };
  platform_kpis: Record<string, number | string>;
  threshold: ThresholdDiscontinuity;
  models: Record<string, ResearchModel>;
  seller_concentration: {
    gini_coefficient: number;
    gini_bootstrap_ci_low: number;
    gini_bootstrap_ci_high: number;
    sellers_for_50pct_gmv: { sellers: number; seller_share_pct: number };
    sellers_for_80pct_gmv: { sellers: number; seller_share_pct: number };
  };
  figures: { file_name: string; title: string; url: string }[];
  caveats: string[];
  attribution: string;
}

export interface MetricDefinition {
  metric_id: string;
  label: string;
  description: string;
  formula: string;
  unit: MetricUnit;
  grain: string;
  source: string;
  source_columns: string[];
  transformations: string[];
  exclusions: string[];
  assumptions: string[];
  limitations: string[];
}

export interface ExcludedRecords {
  reason: string;
  label: string;
  records: number;
}

export interface MetricExplanation {
  definition: MetricDefinition;
  status: "ok" | "unavailable";
  value: number | null;
  currency: string | null;
  sql: string;
  record_counts: {
    grain: string;
    input_records: number;
    contributing_records: number;
    excluded_total: number;
    excluded: ExcludedRecords[];
    overlapping_flags: ExcludedRecords[];
    is_consistent: boolean;
  } | null;
  lineage: string[];
  unavailable_reason: string | null;
  context: Record<string, unknown>;
}

export interface SimulatorResponse {
  scenario: {
    delay_days: number;
    is_sla_breached: number;
    predicted_severe_detractor_probability: number;
    observed_severe_detractor_rate_pct_at_this_delay: number | null;
  };
  on_time_baseline: { delay_days: number; predicted_severe_detractor_probability: number };
  absolute_risk_lift_pp: number;
  relative_risk_vs_baseline: number;
  odds_ratio_vs_baseline: number;
  model_note: string;
}

export interface MarketRateFields {
  sla_breach_rate: number | null;
  sla_breach_ci: [number | null, number | null];
  severe_detractor_rate: number | null;
  severe_detractor_ci: [number | null, number | null];
  mean_review_score: number | null;
  reliable: boolean;
}

export interface CategoryScore extends MarketRateFields {
  category: string;
  display_name: string;
  orders: number;
  items_sold: number;
  gmv: number;
  gmv_share: number;
  freight_share: number | null;
  average_item_price: number | null;
  mean_delivery_days: number | null;
  gmv_rank: number;
  reviewed_orders: number;
}

export interface StateScore extends MarketRateFields {
  state: string;
  state_name: string;
  delivered_orders: number;
  customers: number;
  gmv: number;
  gmv_share: number;
  average_order_value: number;
  median_delivery_days: number | null;
  median_promised_days: number | null;
  median_distance_km: number | null;
  mean_freight_ratio: number | null;
}

export type MarketAssociation =
  { available: true; rho: number; p_value: number; n_groups: number; description: string; caveat: string } | { available: false; reason: string };

export interface OlistMarkets {
  currency: string;
  categories: {
    rows: CategoryScore[];
    total_categories: number;
    reliable_categories: number;
    min_orders: number;
    gmv_total: number;
    best_reviewed: CategoryScore[];
    worst_reviewed: CategoryScore[];
    association: MarketAssociation;
    note: string;
  };
  states: {
    rows: StateScore[];
    total_states: number;
    reliable_states: number;
    min_orders: number;
    gmv_total: number;
    orders_total: number;
    association: MarketAssociation;
    note: string;
  };
}
