import csv
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "public" / "samples" / "mieru-sample-retail-orders-synthetic.csv"
DEMO_DIR = ROOT / "demo"
CSV_COPY = DEMO_DIR / "mieru-demo-retail-orders.csv"
WORKBOOK = DEMO_DIR / "mieru-demo-retail-orders-ja.xlsx"
PUBLIC_WORKBOOK = SOURCE.with_name("mieru-sample-retail-orders-synthetic-ja.xlsx")

HEADERS = {
    "Order ID": "注文番号",
    "Line No": "明細番号",
    "Order Date": "注文日",
    "Customer ID": "顧客ID",
    "Product": "商品名",
    "Category": "カテゴリ",
    "Region": "都道府県",
    "Channel": "販売チャネル",
    "Quantity": "数量",
    "Unit Price": "単価",
    "Discount": "値引き",
    "Unit Cost": "原価",
    "Status": "ステータス",
}
PRODUCTS = {
    "Cast Iron Pan": "鉄製フライパン",
    "Ceramic Mug": "陶器マグカップ",
    "Desk Lamp": "デスクライト",
    "Green Tea Set": "緑茶セット",
    "Linen Shirt": "リネンシャツ",
    "Matcha Kit": "抹茶キット",
    "Running Shoes": "ランニングシューズ",
    "Single-Origin Coffee": "シングルオリジンコーヒー",
    "Smart Watch": "スマートウォッチ",
    "USB-C Charger": "USB-C充電器",
    "Wireless Earbuds": "ワイヤレスイヤホン",
    "Wool Scarf": "ウールマフラー",
}
CATEGORIES = {"home": "ホーム用品", "apparel": "アパレル", "electronics": "家電", "food & drink": "食品・飲料"}
REGIONS = {"aichi": "愛知県", "fukuoka": "福岡県", "hokkaido": "北海道", "kanagawa": "神奈川県", "kyoto": "京都府", "osaka": "大阪府", "tokyo": "東京都"}
CHANNELS = {"Marketplace": "マーケットプレイス", "Online Store": "オンラインストア", "Retail Shop": "実店舗"}
STATUSES = {"Delivered": "配送済み", "Shipped": "発送済み", "Cancelled": "キャンセル", "Returned": "返品"}
MONEY_COLUMNS = {"Unit Price", "Discount", "Unit Cost"}
MONEY_PATTERN = re.compile(r"^-?¥[\d,]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INTEGER_PATTERN = re.compile(r"^-?\d+$")
TITLE = "2024年1月〜2025年6月 売上明細(架空のサンプルデータ)"
NOTES = [
    ("このブックについて", "MIERU のデモ用に作成した架空の小売売上データです。実在の企業・顧客とは関係ありません。"),
    ("対象期間", "2024-01-01 〜 2025-06-30"),
    ("金額", "単価・原価は1個あたり、値引きは明細ごとの円建て金額です(通貨列: JPY)。"),
    ("意図的な品質問題", "重複行、空白行、欠損した単価・注文日、表記ゆれ(前後の空白)を含みます。"),
    ("英語版", "同じ内容の CSV: mieru-demo-retail-orders.csv"),
]


def translate(column: str, value: str) -> object:
    if value == "":
        return None
    if column in MONEY_COLUMNS:
        return int(value.replace("¥", "").replace(",", "")) if MONEY_PATTERN.match(value) else value
    if column == "Order Date":
        return datetime.strptime(value, "%Y-%m-%d") if DATE_PATTERN.match(value) else value
    if column in {"Quantity", "Line No"}:
        return int(value) if INTEGER_PATTERN.match(value) else value
    if column == "Product":
        return PRODUCTS.get(value, value)
    if column == "Category":
        return CATEGORIES.get(value.strip().lower(), value)
    if column == "Region":
        stripped = value.strip()
        translated = REGIONS.get(stripped.lower(), stripped)
        return value.replace(stripped, translated)
    if column == "Channel":
        return CHANNELS.get(value, value)
    if column == "Status":
        return STATUSES.get(value, value)
    return value


def build() -> int:
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)
    missing = [column for column in header if column not in HEADERS]
    if missing:
        raise SystemExit(f"Unexpected columns in {SOURCE.name}: {missing}")

    workbook = Workbook()
    del workbook[workbook.sheetnames[0]]
    sheet = workbook.create_sheet("売上明細")
    sheet.append([TITLE])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([])
    sheet.append([HEADERS[column] for column in header] + ["通貨"])
    header_fill = PatternFill("solid", fgColor="0D1729")
    for cell in sheet[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        values = [translate(column, value) for column, value in zip(header, row)]
        sheet.append(values + (["JPY"] if any(value is not None for value in values) else []))
    for index, column in enumerate(header, start=1):
        letter = get_column_letter(index)
        width = 14 if column not in {"Product", "Channel"} else 22
        sheet.column_dimensions[letter].width = width
        if column in MONEY_COLUMNS:
            for cell in sheet[letter][3:]:
                cell.number_format = "¥#,##0"
        if column == "Order Date":
            for cell in sheet[letter][3:]:
                cell.number_format = "yyyy-mm-dd"
    sheet.column_dimensions[get_column_letter(len(header) + 1)].width = 8
    sheet.freeze_panes = "A4"

    notes = workbook.create_sheet("メモ")
    notes.append(["項目", "内容"])
    for cell in notes[1]:
        cell.font = Font(bold=True)
    for item in NOTES:
        notes.append(list(item))
    notes.column_dimensions["A"].width = 20
    notes.column_dimensions["B"].width = 90

    DEMO_DIR.mkdir(exist_ok=True)
    workbook.save(WORKBOOK)
    shutil.copyfile(WORKBOOK, PUBLIC_WORKBOOK)
    shutil.copyfile(SOURCE, CSV_COPY)
    print(f"Wrote {WORKBOOK.name} ({len(rows)} rows), {CSV_COPY.name} and {PUBLIC_WORKBOOK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
