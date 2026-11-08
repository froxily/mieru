import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

CURRENCY_SYMBOL_CODES: dict[str, str] = {
    "R$": "BRL",
    "US$": "USD",
    "A$": "AUD",
    "C$": "CAD",
    "HK$": "HKD",
    "S$": "SGD",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "円": "JPY",
}
ISO_CURRENCY_CODES: frozenset[str] = frozenset(
    {"USD", "EUR", "GBP", "JPY", "BRL", "INR", "CNY", "KRW", "AUD", "CAD", "CHF", "HKD", "SGD", "MXN", "SEK", "NOK", "DKK", "NZD", "THB", "TWD"}
)
CURRENCY_PATTERN = re.compile(
    r"(R\$|US\$|A\$|C\$|HK\$|S\$|\$|€|£|¥|₹|₩|円|\b(?:" + "|".join(sorted(ISO_CURRENCY_CODES)) + r")\b)",
    re.IGNORECASE,
)
DOT_DECIMAL = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$|^[+-]?\.\d+$")
COMMA_DECIMAL = re.compile(r"^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
SCIENTIFIC = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
YEAR_MIN: int = 1970
YEAR_MAX: int = 2100
EXCEL_SERIAL_MIN: float = 25569.0
EXCEL_SERIAL_MAX: float = 73051.0
DATE_SAMPLE_SIZE: int = 3000

ISO_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y%m%d",
)
DAY_FIRST_FORMATS: tuple[str, ...] = (
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y",
    "%d-%m-%Y %H:%M",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
    "%d/%m/%y",
)
MONTH_FIRST_FORMATS: tuple[str, ...] = (
    "%m/%d/%Y",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S %p",
)
TEXT_MONTH_FORMATS: tuple[str, ...] = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
)
MONTH_ONLY_FORMATS: tuple[str, ...] = ("%Y-%m", "%Y/%m", "%Y年%m月")


def normalize_text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return normalized or None


def normalize_series(series: pd.Series) -> pd.Series:
    return series.map(normalize_text)


@dataclass
class NumericParse:
    values: pd.Series
    parse_rate: float
    convention: str
    currency_codes: list[str] = field(default_factory=list)
    percent_share: float = 0.0
    ambiguous_convention: bool = False


def strip_currency(text: str) -> tuple[str, str | None]:
    match = CURRENCY_PATTERN.search(text)
    if not match:
        return text, None
    token = match.group(0)
    code = CURRENCY_SYMBOL_CODES.get(token) or (token.upper() if token.upper() in ISO_CURRENCY_CODES else None)
    return CURRENCY_PATTERN.sub("", text), code


def clean_numeric_token(text: str) -> tuple[str, bool, bool, str | None]:
    stripped, currency = strip_currency(text)
    negative = False
    candidate = stripped.strip().replace(" ", "").replace("'", "").replace("−", "-")
    if candidate.startswith("(") and candidate.endswith(")"):
        negative = True
        candidate = candidate[1:-1]
    is_percent = candidate.endswith("%")
    if is_percent:
        candidate = candidate[:-1]
    if candidate.endswith("-") and candidate[:-1].replace(".", "").replace(",", "").isdigit():
        negative = True
        candidate = candidate[:-1]
    if candidate.startswith("-") and candidate[1:].startswith("-"):
        candidate = candidate[1:]
    return candidate, negative, is_percent, currency


def parse_with_convention(candidate: str, convention: str) -> float | None:
    if SCIENTIFIC.match(candidate):
        return float(candidate)
    if convention == "dot":
        if not DOT_DECIMAL.match(candidate):
            return None
        return float(candidate.replace(",", ""))
    if not COMMA_DECIMAL.match(candidate):
        return None
    return float(candidate.replace(".", "").replace(",", "."))


def parse_numeric_series(series: pd.Series) -> NumericParse:
    normalized = normalize_series(series)
    unique_values = [value for value in normalized.dropna().unique()]
    tokens = {value: clean_numeric_token(value) for value in unique_values}
    dot_only = comma_only = ambiguous = 0
    for candidate, _negative, _percent, _currency in tokens.values():
        matches_dot = bool(DOT_DECIMAL.match(candidate))
        matches_comma = bool(COMMA_DECIMAL.match(candidate))
        if matches_dot and not matches_comma:
            dot_only += 1
        elif matches_comma and not matches_dot:
            comma_only += 1
        elif matches_dot and matches_comma and "." in candidate:
            ambiguous += 1
    convention = "comma" if comma_only > dot_only else "dot"
    mapping: dict[str, float | None] = {}
    percent_count = 0
    currency_codes: set[str] = set()
    for value, (candidate, negative, is_percent, currency) in tokens.items():
        number = parse_with_convention(candidate, convention)
        if number is not None:
            if negative:
                number = -abs(number)
            if is_percent:
                number = number / 100.0
                percent_count += 1
            if currency:
                currency_codes.add(currency)
        mapping[value] = number
    parsed = normalized.map(lambda value: mapping.get(value) if value is not None else None).astype("float64")
    non_null = int(normalized.notna().sum())
    parse_rate = float(parsed.notna().sum() / non_null) if non_null else 0.0
    return NumericParse(
        values=parsed,
        parse_rate=parse_rate,
        convention=convention,
        currency_codes=sorted(currency_codes),
        percent_share=percent_count / max(1, len(unique_values)),
        ambiguous_convention=dot_only == 0 and comma_only == 0 and ambiguous > 0,
    )


@dataclass
class DateParse:
    values: pd.Series
    parse_rate: float
    formats_used: dict[str, int] = field(default_factory=dict)
    day_month_order: str | None = None
    ambiguous_day_month: bool = False
    excel_serial: bool = False
    month_only: bool = False


def parse_formats(values: list[str], formats: tuple[str, ...]) -> dict[str, pd.Series]:
    index = pd.Index(values)
    results: dict[str, pd.Series] = {}
    for date_format in formats:
        parsed = pd.to_datetime(pd.Series(values, index=index, dtype="object"), format=date_format, errors="coerce")
        parsed = parsed.where((parsed.dt.year >= YEAR_MIN) & (parsed.dt.year <= YEAR_MAX))
        if parsed.notna().any():
            results[date_format] = parsed
    return results


def candidate_formats(sample: list[str]) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[str, pd.Series], dict[str, pd.Series]]:
    return (
        parse_formats(sample, ISO_FORMATS + TEXT_MONTH_FORMATS),
        parse_formats(sample, DAY_FIRST_FORMATS),
        parse_formats(sample, MONTH_FIRST_FORMATS),
        parse_formats(sample, MONTH_ONLY_FORMATS),
    )


def coverage(results: dict[str, pd.Series]) -> pd.Series | None:
    combined: pd.Series | None = None
    for parsed in results.values():
        combined = parsed if combined is None else combined.fillna(parsed)
    return combined


def excel_serial_dates(numeric: pd.Series) -> pd.Series:
    in_range = numeric.where((numeric >= EXCEL_SERIAL_MIN) & (numeric <= EXCEL_SERIAL_MAX))
    return pd.to_datetime(in_range, unit="D", origin="1899-12-30", errors="coerce")


def parse_date_series(series: pd.Series, allow_excel_serial: bool = False) -> DateParse:
    normalized = normalize_series(series)
    non_null = int(normalized.notna().sum())
    empty = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if non_null == 0:
        return DateParse(values=empty, parse_rate=0.0)
    unique_values = [value for value in normalized.dropna().unique()]
    sample = unique_values[:DATE_SAMPLE_SIZE]
    iso_sample, day_first_sample, month_first_sample, month_only_sample = candidate_formats(sample)
    iso_covered = coverage(iso_sample)
    remaining = [value for value in sample if iso_covered is None or pd.isna(iso_covered.get(value))]
    day_first_hits = coverage({key: value.reindex(remaining) for key, value in day_first_sample.items()})
    month_first_hits = coverage({key: value.reindex(remaining) for key, value in month_first_sample.items()})
    day_first_count = int(day_first_hits.notna().sum()) if day_first_hits is not None else 0
    month_first_count = int(month_first_hits.notna().sum()) if month_first_hits is not None else 0
    order: str | None = None
    ambiguous = False
    if day_first_count or month_first_count:
        if day_first_count > month_first_count:
            order = "day_first"
        elif month_first_count > day_first_count:
            order = "month_first"
        else:
            ambiguous = True
    selected_formats = [key for key in ISO_FORMATS + TEXT_MONTH_FORMATS if key in iso_sample]
    if order == "day_first":
        selected_formats += [key for key in DAY_FIRST_FORMATS if key in day_first_sample]
    elif order == "month_first":
        selected_formats += [key for key in MONTH_FIRST_FORMATS if key in month_first_sample]
    month_only = False
    if not selected_formats and month_only_sample:
        selected_formats = [key for key in MONTH_ONLY_FORMATS if key in month_only_sample]
        month_only = True
    mapping: dict[str, pd.Timestamp] = {}
    formats_used: dict[str, int] = {}
    if selected_formats:
        full_results = parse_formats(unique_values, tuple(selected_formats))
        assigned = pd.Series(pd.NaT, index=pd.Index(unique_values), dtype="datetime64[ns]")
        for date_format in selected_formats:
            parsed = full_results.get(date_format)
            if parsed is None:
                continue
            newly = parsed.notna() & assigned.isna()
            if newly.any():
                formats_used[date_format] = int(normalized.isin(parsed.index[newly.to_numpy()]).sum())
                assigned = assigned.where(~newly, parsed)
        mapping = {value: stamp for value, stamp in assigned.items() if not pd.isna(stamp)}
    values = normalized.map(mapping).astype("datetime64[ns]") if mapping else empty.copy()
    excel_serial = False
    if allow_excel_serial and values.notna().sum() < 0.5 * non_null:
        numeric = parse_numeric_series(series).values
        serial_dates = excel_serial_dates(numeric)
        if serial_dates.notna().sum() >= 0.9 * non_null:
            values = serial_dates.astype("datetime64[ns]")
            excel_serial = True
            formats_used = {"excel_serial": int(serial_dates.notna().sum())}
    parse_rate = float(values.notna().sum() / non_null)
    return DateParse(
        values=values,
        parse_rate=parse_rate,
        formats_used=formats_used,
        day_month_order=order,
        ambiguous_day_month=ambiguous,
        excel_serial=excel_serial,
        month_only=month_only,
    )


def is_integer_like(values: pd.Series) -> float:
    finite = values.dropna()
    if finite.empty:
        return 0.0
    return float(np.isclose(finite, np.round(finite)).mean())
