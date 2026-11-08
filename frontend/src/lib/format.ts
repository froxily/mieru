export type MetricUnit = "currency" | "count" | "ratio" | "score" | "days" | "index" | "share";

const LOCALE = "en-US";

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatNumber(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (!isFiniteNumber(value)) return "—";
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits, minimumFractionDigits: 0 }).format(value);
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return "—";
  if (Math.abs(value) < 10_000) return formatNumber(value, 0);
  return new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function currencySymbol(currency: string | null | undefined): string {
  if (!currency) return "";
  if (currency === "BRL") return "R$";
  try {
    const parts = new Intl.NumberFormat(LOCALE, { style: "currency", currency, currencyDisplay: "narrowSymbol" }).formatToParts(0);
    return parts.find((part) => part.type === "currency")?.value ?? currency;
  } catch {
    return currency;
  }
}

export function formatCurrency(
  value: number | null | undefined,
  currency: string | null | undefined,
  options: { compact?: boolean; fractionDigits?: number } = {},
): string {
  if (!isFiniteNumber(value)) return "—";
  const { compact = false, fractionDigits } = options;
  const symbol = currencySymbol(currency);
  const absolute = Math.abs(value);
  const digits = fractionDigits ?? (absolute >= 1000 ? 0 : 2);
  const body =
    compact && absolute >= 10_000
      ? new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 2 }).format(absolute)
      : new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(absolute);
  const sign = value < 0 ? "−" : "";
  return symbol ? `${sign}${symbol} ${body}` : `${sign}${body}`;
}

export function formatPercent(ratio: number | null | undefined, fractionDigits = 1): string {
  if (!isFiniteNumber(ratio)) return "—";
  return `${(ratio * 100).toFixed(fractionDigits)}%`;
}

export function formatShare(ratio: number | null | undefined, fractionDigits = 1): string {
  if (!isFiniteNumber(ratio)) return "—";
  const floor = 10 ** -fractionDigits;
  if (ratio > 0 && ratio * 100 < floor) return `<${floor.toFixed(fractionDigits)}%`;
  return formatPercent(ratio, fractionDigits);
}

export function formatPercentPoints(points: number | null | undefined, fractionDigits = 1): string {
  if (!isFiniteNumber(points)) return "—";
  const sign = points > 0 ? "+" : points < 0 ? "−" : "";
  return `${sign}${Math.abs(points).toFixed(fractionDigits)} pp`;
}

export function formatSigned(value: number | null | undefined, fractionDigits = 2): string {
  if (!isFiniteNumber(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(fractionDigits)}`;
}

export function formatPValue(pValue: number | null | undefined): string {
  if (!isFiniteNumber(pValue)) return "—";
  if (pValue === 0) return "p < 1e-300";
  if (pValue < 0.0001) return "p < 0.0001";
  return `p = ${pValue.toFixed(4)}`;
}

export function formatMetricValue(
  value: number | null | undefined,
  unit: MetricUnit | string,
  currency?: string | null,
  options: { compact?: boolean } = {},
): string {
  if (!isFiniteNumber(value)) return "—";
  switch (unit) {
    case "currency":
      return formatCurrency(value, currency, { compact: options.compact });
    case "count":
      return options.compact ? formatCompactNumber(value) : formatNumber(value, 0);
    case "ratio":
    case "share":
      return formatPercent(value, value !== 0 && Math.abs(value) < 0.1 ? 2 : 1);
    case "score":
      return value.toFixed(2);
    case "days":
      return `${formatNumber(value, 1)} days`;
    case "index":
      return value.toFixed(3);
    default:
      return formatNumber(value, 2);
  }
}

export function prettifyLabel(raw: string): string {
  const cleaned = raw.replace(/_/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}
