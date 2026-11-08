import type { MetricUnit } from "../lib/format";

export type DatasetStatus = "queued" | "processing" | "ready" | "failed";

export interface DatasetMeta {
  dataset_id: string;
  display_name: string;
  status: DatasetStatus;
  stage: string;
  error: string | null;
  created_at: string;
  expires_at: string;
  size_bytes: number | null;
  data_version: number;
}

export interface Capability {
  available: boolean;
  reason: string | null;
}

export interface Clarification {
  kind: string;
  role: string;
  label: string;
  columns: string[];
  message: string;
}

export interface SourceSummary {
  display_name: string;
  format: "csv" | "xlsx";
  size_bytes: number;
  sha256: string;
  encoding: string | null;
  delimiter: string | null;
  sheet_name: string | null;
  sheet_names: string[];
  header_row_number: number;
  skipped_leading_rows: number;
  synthesized_header: boolean;
  rows: number;
  columns: number;
  ragged_rows: number;
  notes: string[];
}

export interface DatasetStatusPayload {
  dataset: DatasetMeta;
  stages: string[];
  schema?: {
    source: SourceSummary;
    grain: string;
    grain_explanation: string;
    revenue_basis: string | null;
    revenue_label: string;
    currency: string | null;
    currency_status: string;
    capabilities: Record<string, Capability>;
    assumptions: string[];
    clarifications: Clarification[];
    role_columns: Record<string, string>;
    assignments: Record<string, { column_index: number; column_name: string; label: string }>;
    unmapped_columns: string[];
    columns: string[];
    role_options: { role: string; label: string }[];
    policies: Record<string, boolean>;
  };
}

export interface DatasetKpi {
  metric_id: string;
  label: string;
  value: number | null;
  unit: MetricUnit;
  currency: string | null;
  status: "ok" | "unavailable";
  unavailable_reason: string | null;
}

export interface TrendPoint {
  period: string;
  period_end: string;
  revenue: number | null;
  orders: number;
  contributing_rows: number;
  is_partial: boolean;
}

export interface Trend {
  available: boolean;
  reason?: string | null;
  granularity?: "day" | "week" | "month";
  first_date?: string;
  last_date?: string;
  points?: TrendPoint[];
  revenue_available?: boolean;
  comparison?: {
    available: boolean;
    reason?: string;
    current_period?: string;
    previous_period?: string;
    revenue_change?: number | null;
    orders_change?: number | null;
    note?: string;
  };
}

export interface BreakdownRow {
  label: string;
  revenue: number | null;
  revenue_share: number | null;
  orders: number;
  units: number | null;
  rows: number;
}

export interface Breakdown {
  available: boolean;
  reason?: string | null;
  dimension?: string;
  column?: string | null;
  rows?: BreakdownRow[];
  others?: { label: string; revenue: number | null; revenue_share: number | null; rows: number; groups: number } | null;
  total_groups?: number;
  revenue_total?: number | null;
  revenue_shown?: boolean;
  note?: string | null;
}

export interface DatasetFilters {
  start: string | null;
  end: string | null;
  categories: string[];
  regions: string[];
  channels: string[];
}

export interface DatasetDashboard {
  dataset: DatasetMeta & {
    grain: string;
    grain_explanation: string;
    revenue_basis: string | null;
    revenue_label: string;
    currency: string | null;
    currency_status: string;
    rows: number;
    columns: number;
    format: string;
    orders_label: string;
  };
  kpis: DatasetKpi[];
  trend: Trend;
  breakdowns: Record<"products" | "categories" | "regions" | "channels", Breakdown>;
  filters: {
    applied: DatasetFilters;
    options: { categories?: string[]; regions?: string[]; channels?: string[]; date_min?: string; date_max?: string };
  };
  capabilities: Record<string, Capability>;
  assumptions: string[];
  clarifications: Clarification[];
  role_columns: Record<string, string>;
}

export interface QualityIssue {
  code: string;
  label: string;
  rows: number;
  share: number;
  severity: "info" | "warning" | "critical";
  treatment: string;
  policy: string | null;
  explanation: string;
}

export interface QualityImpact {
  metric_id: string;
  label: string;
  unit: MetricUnit;
  currency: string | null;
  without_policies: number | null;
  with_policies: number | null;
  delta: number | null;
  delta_share: number | null;
}

export interface QualityPolicy {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
  default: boolean;
  impact_metric: string;
  value_now: number | null;
  value_if_toggled: number | null;
  delta_if_toggled: number | null;
}

export interface QualityColumn {
  name: string;
  role: string | null;
  role_label: string | null;
  non_null_share: number;
  distinct: number;
  numeric_rate: number;
  date_rate: number;
  date_formats: Record<string, number>;
  numeric_convention: string;
  currency_codes: string[];
  sample_values: string[];
}

export interface AuditEntry {
  step: string;
  at: string;
  title: string;
  detail: string;
}

export interface DatasetQuality {
  source: SourceSummary;
  summary: {
    rows_in_file: number;
    headline_metric: string;
    record_counts: {
      grain: string;
      input_records: number;
      contributing_records: number;
      excluded_total: number;
      excluded: { reason: string; label: string; records: number }[];
      overlapping_flags: { reason: string; label: string; records: number }[];
      is_consistent: boolean;
    } | null;
  };
  issues: QualityIssue[];
  impact: QualityImpact[];
  policies: QualityPolicy[];
  columns: QualityColumn[];
  audit: AuditEntry[];
  canonical: {
    grain: string;
    grain_explanation: string;
    revenue_basis: string | null;
    revenue_label: string;
    currency: string | null;
    currency_status: string;
    assumptions: string[];
    clarifications: Clarification[];
    relational_checks: Record<string, number | null>;
    normalization_changes: Record<string, number>;
    decisions: { step: string; decision: string; detail: string }[];
  };
}

export interface Unavailable {
  available: false;
  reason: string | null;
}

export interface BridgeStep {
  label: string;
  value: number;
  kind: "total" | "decrease";
  metric_id: string | null;
}

export interface RevenueBridge {
  available: true;
  currency: string | null;
  steps: BridgeStep[];
  gross_sales: number;
  discounts_deducted: number;
  discounts_recorded: number;
  returns_value: number;
  net_revenue: number;
  contributing_rows: number;
  return_rows: number;
  reconciles: boolean;
  identity: string;
  notes: string[];
}

export interface ProfitGroup {
  label: string;
  revenue: number;
  cost: number;
  gross_profit: number;
  margin: number | null;
  revenue_share: number | null;
  rows: number;
}

export interface Profitability {
  available: true;
  currency: string | null;
  revenue: number;
  cost: number;
  gross_profit: number;
  margin: number | null;
  rows: number;
  cost_coverage: { rows_with_cost: number; contributing_rows: number; revenue_share: number | null };
  groups: Partial<Record<PerformanceDimension, { rows: ProfitGroup[]; lowest_margin: ProfitGroup[]; loss_making_groups: number; total_groups: number }>>;
  note: string;
}

export interface ReturnGroup {
  label: string;
  gross_sales: number;
  net_sales: number;
  returns_value: number;
  return_rate: number | null;
  sale_rows: number;
  return_rows: number;
  small_sample: boolean;
}

export interface ReturnsAnalysis {
  available: true;
  currency: string | null;
  gross_sales: number;
  net_sales: number;
  returns_value: number;
  return_rate: number | null;
  sale_rows: number;
  return_rows: number;
  groups: Partial<Record<PerformanceDimension, { rows: ReturnGroup[]; total_groups: number; groups_with_returns: number }>>;
  note: string;
}

export interface DiscountSummary {
  discount_value: number;
  list_value: number;
  discount_rate: number | null;
  discounted_rows: number;
  sale_rows: number;
  discounted_row_share: number | null;
}

export interface MarginSplitSide {
  revenue: number;
  gross_profit: number;
  margin: number | null;
  rows: number;
}

export interface DiscountsAnalysis extends DiscountSummary {
  available: true;
  currency: string | null;
  treatment: "deducted" | "already_net";
  groups: Partial<Record<PerformanceDimension, { rows: (DiscountSummary & { label: string })[]; total_groups: number }>>;
  trend: { available: boolean; reason: string | null; points?: (DiscountSummary & { period: string })[]; note?: string };
  margin_split: { discounted: MarginSplitSide; full_price: MarginSplitSide } | null;
  note: string;
}

export interface ParetoSummary {
  available: true;
  items: number;
  excluded_non_positive: number;
  revenue_total: number;
  top_10pct_share: number;
  top_20pct_share: number;
  items_for_50pct: number;
  items_for_80pct: number;
  gini: number;
  curve: { item_share: number; revenue_share: number }[];
  top_items: { label: string; revenue: number; share: number }[] | null;
}

export interface Concentration {
  available: true;
  currency: string | null;
  products: ParetoSummary | Unavailable;
  customers: ParetoSummary | Unavailable;
  note: string;
}

export type PerformanceDimension = "categories" | "products" | "channels" | "regions";

export interface DatasetPerformance {
  currency: string | null;
  orders_label: string;
  bridge: RevenueBridge | Unavailable;
  profitability: Profitability | Unavailable;
  returns: ReturnsAnalysis | Unavailable;
  discounts: DiscountsAnalysis | Unavailable;
  concentration: Concentration | Unavailable;
  filters: { start: string | null; end: string | null; categories: string[]; regions: string[]; channels: string[] };
}
