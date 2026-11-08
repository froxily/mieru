import codecs
import csv
import datetime as dt
import io
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from charset_normalizer import from_bytes

from mieru.ingest.errors import UploadRejectedError

ACCEPTED_TEXT_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".txt"})
ACCEPTED_EXTENSIONS: frozenset[str] = ACCEPTED_TEXT_EXTENSIONS | {".xlsx"}
REJECTED_EXTENSION_MESSAGES: dict[str, str] = {
    ".xls": "Legacy .xls workbooks are not supported. Re-save the file as .xlsx or CSV.",
    ".xlsm": "Macro-enabled workbooks (.xlsm) are not accepted for security reasons. Re-save as .xlsx or CSV.",
    ".xlsb": "Binary workbooks (.xlsb) are not supported. Re-save as .xlsx or CSV.",
    ".ods": "OpenDocument spreadsheets are not supported yet. Export as .xlsx or CSV.",
}
CANDIDATE_DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")
SNIFF_LINES: int = 60
HEADER_SCAN_ROWS: int = 25
XLSX_MAX_UNCOMPRESSED_BYTES: int = 600 * 1024 * 1024
XLSX_MAX_MEMBERS: int = 2000
XLSX_MAX_COMPRESSION_RATIO: float = 150.0
XLSX_MAX_CELLS: int = 20_000_000
MAX_FIELDS_PER_ROW_FACTOR: int = 4
SHEET_SCORE_ROWS: int = 200
FALLBACK_ENCODINGS: tuple[str, ...] = ("cp932", "cp1252", "latin-1")
JAPANESE_SCRIPT_SHARE: float = 0.8


@dataclass
class RawTable:
    columns: list[str]
    rows: list[list[str | None]]
    source_format: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None
    sheet_names: list[str] = field(default_factory=list)
    header_row_number: int = 1
    skipped_leading_rows: int = 0
    ragged_row_ids: list[int] = field(default_factory=list)
    synthesized_header: bool = False
    notes: list[str] = field(default_factory=list)


def normalize_extension(file_name: str) -> str:
    return Path(file_name).suffix.lower()


def validate_extension(file_name: str) -> str:
    extension = normalize_extension(file_name)
    if extension in REJECTED_EXTENSION_MESSAGES:
        raise UploadRejectedError(415, REJECTED_EXTENSION_MESSAGES[extension])
    if extension not in ACCEPTED_EXTENSIONS:
        raise UploadRejectedError(415, "Unsupported file type. Upload a CSV, TSV, TXT or XLSX file.")
    return extension


def validate_magic_bytes(path: Path, extension: str) -> None:
    with path.open("rb") as handle:
        head = handle.read(8192)
    if not head:
        raise UploadRejectedError(422, "The file is empty.")
    if extension == ".xlsx":
        if not head.startswith(b"PK\x03\x04"):
            raise UploadRejectedError(422, "This file has an .xlsx extension but is not a valid Excel workbook.")
        return
    if head.startswith(b"PK\x03\x04") or head.startswith(b"\xd0\xcf\x11\xe0"):
        raise UploadRejectedError(422, "This looks like a spreadsheet saved with a text extension. Upload it as .xlsx.")
    if b"\x00" in head and not (head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE)):
        raise UploadRejectedError(422, "The file contains binary data and is not a readable text table.")


def decode_if_japanese(raw_bytes: bytes) -> str | None:
    try:
        text = raw_bytes.decode("cp932")
    except UnicodeDecodeError:
        return None
    non_ascii = [char for char in text if ord(char) > 127]
    if not non_ascii:
        return None
    japanese = sum(1 for char in non_ascii if "぀" <= char <= "ヿ" or "一" <= char <= "鿿" or "＀" <= char <= "￯")
    has_kana = any("぀" <= char <= "ヿ" for char in non_ascii)
    return text if has_kana and japanese / len(non_ascii) >= JAPANESE_SCRIPT_SHARE else None


def decode_text(raw_bytes: bytes) -> tuple[str, str]:
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if raw_bytes.startswith(bom):
            return raw_bytes.decode(encoding), encoding
    try:
        return raw_bytes.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    japanese_text = decode_if_japanese(raw_bytes)
    if japanese_text is not None:
        return japanese_text, "cp932"
    best_match = from_bytes(raw_bytes[: 2 * 1024 * 1024]).best()
    if best_match is not None and best_match.encoding:
        try:
            return raw_bytes.decode(best_match.encoding), best_match.encoding
        except (UnicodeDecodeError, LookupError):
            pass
    for encoding in FALLBACK_ENCODINGS:
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UploadRejectedError(422, "Could not determine the text encoding of this file.")


def score_delimiter(sample_lines: list[str], delimiter: str) -> float:
    if not sample_lines:
        return 0.0
    reader = csv.reader(io.StringIO("\n".join(sample_lines)), delimiter=delimiter)
    widths = [len(row) for row in reader if any(cell.strip() for cell in row)]
    if not widths:
        return 0.0
    modal_width = max(set(widths), key=widths.count)
    if modal_width <= 1:
        return 0.0
    consistency = widths.count(modal_width) / len(widths)
    return consistency * min(modal_width, 50)


def detect_delimiter(text: str, extension: str) -> str:
    if extension == ".tsv":
        return "\t"
    sample_lines = [line for line in text.splitlines()[:SNIFF_LINES] if line.strip()]
    scores = {delimiter: score_delimiter(sample_lines, delimiter) for delimiter in CANDIDATE_DELIMITERS}
    best_delimiter = max(scores, key=lambda delimiter: scores[delimiter])
    return best_delimiter if scores[best_delimiter] > 0 else ","


def is_numeric_like(value: str) -> bool:
    stripped = value.strip().replace(",", "").replace(".", "").replace("-", "").replace("/", "").replace(" ", "")
    return stripped.isdigit()


def header_likeness(row: list[str | None], width: int) -> float:
    cells = [cell.strip() for cell in row if cell is not None and cell.strip()]
    if width == 0 or len(cells) < max(2, int(0.5 * width)):
        return 0.0
    textual = sum(1 for cell in cells if not is_numeric_like(cell))
    unique_ratio = len(set(cells)) / len(cells)
    return (textual / len(cells)) * unique_ratio * (len(cells) / width)


def locate_header(rows: list[list[str | None]]) -> tuple[int, bool]:
    if not rows:
        return 0, True
    width = max(len(row) for row in rows[:HEADER_SCAN_ROWS])
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        non_empty = [cell for cell in row if cell is not None and cell.strip()]
        if len(non_empty) < max(2, int(0.5 * width)) and width > 1:
            continue
        if header_likeness(row, width) >= 0.6:
            return index, False
        return index, True
    return 0, True


def deduplicate_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        base = name or "Column"
        count = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = count
        result.append(base if count == 1 else f"{base} ({count})")
    return result


def occupied_width(row: list[str | None]) -> int:
    width = len(row)
    while width and (row[width - 1] is None or not str(row[width - 1]).strip()):
        width -= 1
    return width


def typical_width(rows: list[list[str | None]]) -> int:
    widths = Counter(width for width in (occupied_width(row) for row in rows) if width > 0)
    if not widths:
        return 0
    return max(widths.items(), key=lambda item: (item[1], item[0]))[0]


def build_table(physical_rows: list[list[str | None]], source_format: str, max_rows: int, max_columns: int) -> RawTable:
    header_index, synthesized = locate_header(physical_rows)
    if max((len(row) for row in physical_rows), default=0) == 0:
        raise UploadRejectedError(422, "No tabular data was found in the file.")
    data_rows = physical_rows[header_index:] if synthesized else physical_rows[header_index + 1 :]
    width = typical_width(data_rows)
    if not synthesized:
        width = max(width, len(physical_rows[header_index]))
    if width > max_columns:
        raise UploadRejectedError(422, f"The table has {width} columns; the limit is {max_columns}.")
    if synthesized:
        columns = [f"Column {index + 1}" for index in range(width)]
    else:
        header = physical_rows[header_index]
        columns = [(cell or "").strip() or f"Column {index + 1}" for index, cell in enumerate(header)]
        columns += [f"Column {index + 1}" for index in range(len(columns), width)]
    columns = deduplicate_names(columns)
    while data_rows and all(cell is None or not str(cell).strip() for cell in data_rows[-1]):
        data_rows.pop()
    if not data_rows:
        raise UploadRejectedError(422, "The file has a header but no data rows.")
    if len(data_rows) > max_rows:
        raise UploadRejectedError(413, f"The table has {len(data_rows):,} rows; the limit is {max_rows:,}.")
    table_width = len(columns)
    normalized_rows: list[list[str | None]] = []
    ragged_row_ids: list[int] = []
    for row_number, row in enumerate(data_rows, start=1):
        cells = [None if cell is None or str(cell).strip() == "" else str(cell) for cell in row]
        if len(cells) > table_width:
            overflow = cells[table_width:]
            if any(cell is not None for cell in overflow):
                ragged_row_ids.append(row_number)
            cells = cells[:table_width]
        elif len(cells) < table_width:
            if len(cells) > 0 and source_format != "xlsx":
                ragged_row_ids.append(row_number)
            cells = cells + [None] * (table_width - len(cells))
        normalized_rows.append(cells)
    return RawTable(
        columns=columns,
        rows=normalized_rows,
        source_format=source_format,
        header_row_number=header_index + 1,
        skipped_leading_rows=header_index,
        ragged_row_ids=ragged_row_ids,
        synthesized_header=synthesized,
    )


def read_delimited(path: Path, extension: str, max_rows: int, max_columns: int) -> RawTable:
    text, encoding = decode_text(path.read_bytes())
    delimiter = detect_delimiter(text, extension)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    physical_rows: list[list[str | None]] = []
    for row in reader:
        if len(row) > max_columns * MAX_FIELDS_PER_ROW_FACTOR:
            raise UploadRejectedError(422, f"Line {reader.line_num:,} has {len(row):,} fields; at most {max_columns} columns are supported.")
        physical_rows.append(list(row))
        if len(physical_rows) > max_rows + HEADER_SCAN_ROWS + 1:
            raise UploadRejectedError(413, f"The file has more than {max_rows:,} rows.")
    table = build_table(physical_rows, "csv", max_rows, max_columns)
    table.encoding = encoding
    table.delimiter = delimiter
    if encoding not in {"utf-8", "utf-8-sig"}:
        table.notes.append(f"Decoded from {encoding} and normalised to UTF-8.")
    return table


def guard_workbook(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as error:
        raise UploadRejectedError(422, "The workbook is damaged or not a valid .xlsx file.") from error
    if len(members) > XLSX_MAX_MEMBERS:
        raise UploadRejectedError(422, "The workbook has an unusual internal structure and was rejected.")
    uncompressed = sum(member.file_size for member in members)
    compressed = max(1, sum(member.compress_size for member in members))
    if uncompressed > XLSX_MAX_UNCOMPRESSED_BYTES or uncompressed / compressed > XLSX_MAX_COMPRESSION_RATIO:
        raise UploadRejectedError(422, "The workbook expands to an unsafe size and was rejected.")
    if any(member.filename.lower().endswith("vbaproject.bin") for member in members):
        raise UploadRejectedError(415, "The workbook contains macros and was rejected for security reasons.")


def cell_to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return None
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.time):
        return value.isoformat()
    text = str(value)
    return text if text.strip() else None


def read_workbook(path: Path, max_rows: int, max_columns: int) -> RawTable:
    from openpyxl import load_workbook

    guard_workbook(path)
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as error:
        raise UploadRejectedError(422, "The workbook could not be opened. Re-save it as .xlsx and try again.") from error
    try:
        sheet_names = list(workbook.sheetnames)
        best_rows: list[list[str | None]] | None = None
        best_sheet: str | None = None
        best_score = -1
        cell_budget = XLSX_MAX_CELLS
        column_cap = max_columns + 1
        for sheet_name in sheet_names:
            worksheet = workbook[sheet_name]
            declared_rows = worksheet.max_row or 0
            declared_columns = min(worksheet.max_column or column_cap, column_cap)
            if declared_rows * max(1, declared_columns) > XLSX_MAX_CELLS:
                raise UploadRejectedError(
                    413,
                    f"Sheet '{sheet_name}' declares {declared_rows:,} rows × {worksheet.max_column or 0:,} columns, which is too large to analyse. "
                    "Delete unused rows and columns or save the sheet as CSV.",
                )
            rows: list[list[str | None]] = []
            for row in worksheet.iter_rows(values_only=True, max_col=column_cap, max_row=max_rows + HEADER_SCAN_ROWS + 2):
                values = [] if row.count(None) == len(row) else [cell_to_text(cell) for cell in row]
                while values and values[-1] is None:
                    values.pop()
                rows.append(values)
                cell_budget -= max(1, len(values))
                if cell_budget < 0:
                    raise UploadRejectedError(413, f"The workbook has more than {XLSX_MAX_CELLS:,} cells; save the sheet you need as CSV.")
                if len(rows) > max_rows + HEADER_SCAN_ROWS + 1:
                    raise UploadRejectedError(413, f"Sheet '{sheet_name}' has more than {max_rows:,} rows.")
            score = sum(1 for row in rows[:SHEET_SCORE_ROWS] for cell in row if cell is not None)
            if score > best_score:
                best_rows, best_sheet, best_score = rows, sheet_name, score
    finally:
        workbook.close()
    if not best_rows or best_score <= 0:
        raise UploadRejectedError(422, "No data was found in any worksheet.")
    trimmed_rows = [row for row in best_rows]
    last_used_column = max((max((index for index, cell in enumerate(row) if cell is not None), default=-1) for row in trimmed_rows), default=-1)
    trimmed_rows = [row[: last_used_column + 1] for row in trimmed_rows]
    table = build_table(trimmed_rows, "xlsx", max_rows, max_columns)
    table.sheet_name = best_sheet
    table.sheet_names = sheet_names
    if len(sheet_names) > 1:
        table.notes.append(f"Workbook has {len(sheet_names)} sheets; analysed '{best_sheet}' (the sheet with the most data).")
    table.notes.append("Formulas are read as their last saved values; formulas are never executed.")
    return table


def read_upload(path: Path, extension: str, max_rows: int, max_columns: int) -> RawTable:
    if extension == ".xlsx":
        return read_workbook(path, max_rows, max_columns)
    return read_delimited(path, extension, max_rows, max_columns)
