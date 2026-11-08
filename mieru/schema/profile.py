import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from mieru.schema.parsing import DateParse, NumericParse, is_integer_like, normalize_series, parse_date_series, parse_numeric_series

SAMPLE_VALUE_COUNT: int = 5
TOP_VALUE_COUNT: int = 6
BOOLEAN_TOKENS: frozenset[str] = frozenset({"true", "false", "yes", "no", "y", "n", "1", "0", "t", "f", "はい", "いいえ", "sim", "não", "si"})
LATIN_BLOCK_END: int = 0x250
NON_WORD = re.compile(r"[^0-9a-z぀-ヿ㐀-鿿가-힯]+")


def strip_latin_accents(text: str) -> str:
    characters: list[str] = []
    for char in text:
        if ord(char) < LATIN_BLOCK_END:
            characters.extend(part for part in unicodedata.normalize("NFKD", char) if not unicodedata.combining(part))
        else:
            characters.append(char)
    return "".join(characters)


def normalize_column_name(name: str) -> str:
    folded = strip_latin_accents(unicodedata.normalize("NFKC", name).lower())
    return NON_WORD.sub("_", folded).strip("_")


@dataclass
class ColumnProfile:
    index: int
    name: str
    normalized_name: str
    non_null: int
    null_count: int
    distinct: int
    distinct_ratio: float
    sample_values: list[str]
    top_values: list[tuple[str, int]]
    numeric_rate: float
    numeric_convention: str
    numeric_ambiguous_convention: bool
    currency_codes: list[str]
    percent_share: float
    integer_share: float
    negative_share: float
    numeric_min: float | None
    numeric_max: float | None
    numeric_median: float | None
    date_rate: float
    date_formats: dict[str, int]
    date_ambiguous_day_month: bool
    date_order: str | None
    date_excel_serial: bool
    boolean_like: bool
    mean_text_length: float
    numeric: NumericParse | None = field(default=None, repr=False)
    date: DateParse | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("numeric", None)
        payload.pop("date", None)
        payload["top_values"] = [[value, count] for value, count in self.top_values]
        return payload


def finite_or_none(value: float) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def profile_column(index: int, name: str, raw: pd.Series) -> ColumnProfile:
    normalized = normalize_series(raw)
    non_null = int(normalized.notna().sum())
    total = len(normalized)
    counts = normalized.value_counts(dropna=True)
    distinct = int(len(counts))
    numeric = parse_numeric_series(raw)
    numeric_values = numeric.values.dropna()
    date = parse_date_series(raw, allow_excel_serial=True)
    lowered = {str(value).lower() for value in counts.index[:20]}
    boolean_like = distinct > 0 and distinct <= 3 and lowered <= BOOLEAN_TOKENS
    text_lengths = normalized.dropna().map(len)
    return ColumnProfile(
        index=index,
        name=name,
        normalized_name=normalize_column_name(name),
        non_null=non_null,
        null_count=total - non_null,
        distinct=distinct,
        distinct_ratio=distinct / non_null if non_null else 0.0,
        sample_values=[str(value) for value in counts.index[:SAMPLE_VALUE_COUNT]],
        top_values=[(str(value), int(count)) for value, count in counts.head(TOP_VALUE_COUNT).items()],
        numeric_rate=numeric.parse_rate,
        numeric_convention=numeric.convention,
        numeric_ambiguous_convention=numeric.ambiguous_convention,
        currency_codes=numeric.currency_codes,
        percent_share=numeric.percent_share,
        integer_share=is_integer_like(numeric_values),
        negative_share=float((numeric_values < 0).mean()) if len(numeric_values) else 0.0,
        numeric_min=finite_or_none(numeric_values.min()) if len(numeric_values) else None,
        numeric_max=finite_or_none(numeric_values.max()) if len(numeric_values) else None,
        numeric_median=finite_or_none(numeric_values.median()) if len(numeric_values) else None,
        date_rate=date.parse_rate,
        date_formats=date.formats_used,
        date_ambiguous_day_month=date.ambiguous_day_month,
        date_order=date.day_month_order,
        date_excel_serial=date.excel_serial,
        boolean_like=bool(boolean_like),
        mean_text_length=float(text_lengths.mean()) if len(text_lengths) else 0.0,
        numeric=numeric,
        date=date,
    )


def profile_table(frame: pd.DataFrame, column_names: list[str]) -> list[ColumnProfile]:
    return [profile_column(index, name, frame.iloc[:, index]) for index, name in enumerate(column_names)]
