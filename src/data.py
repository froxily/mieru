import csv
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
RAW_DATA_DIR: Path = PROJECT_ROOT / "data" / "raw"
SOURCE_BASE_URL: str = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"
DOWNLOAD_TIMEOUT_SECONDS: int = 180
DOWNLOAD_CHUNK_BYTES: int = 1 << 20

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "olist_customers_dataset.csv": (
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ),
    "olist_orders_dataset.csv": (
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ),
    "olist_order_items_dataset.csv": (
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ),
    "olist_order_payments_dataset.csv": (
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ),
    "olist_order_reviews_dataset.csv": (
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ),
    "olist_products_dataset.csv": (
        "product_id",
        "product_category_name",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ),
    "olist_sellers_dataset.csv": (
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ),
    "olist_geolocation_dataset.csv": (
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    ),
}


class RawDataDownloadError(RuntimeError):
    pass


class RawSchemaError(RuntimeError):
    pass


def raw_file_path(file_name: str, raw_dir: Path = RAW_DATA_DIR) -> Path:
    return raw_dir / file_name


def is_usable_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def download_file(url: str, destination: Path) -> int:
    partial_destination = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            with partial_destination.open("wb") as handle:
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    handle.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
        partial_destination.unlink(missing_ok=True)
        raise RawDataDownloadError(
            f"Download FAILED for {url} ({error}). Supply this file manually at {destination} and re-run."
        ) from error
    if partial_destination.stat().st_size == 0:
        partial_destination.unlink(missing_ok=True)
        raise RawDataDownloadError(f"Download returned an empty body for {url}.")
    partial_destination.replace(destination)
    return destination.stat().st_size


def download_raw_files(raw_dir: Path = RAW_DATA_DIR) -> dict[str, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    download_status: dict[str, str] = {}
    for file_name in REQUIRED_COLUMNS:
        destination = raw_file_path(file_name, raw_dir)
        if is_usable_file(destination):
            download_status[file_name] = "cached"
            continue
        byte_count = download_file(SOURCE_BASE_URL + file_name, destination)
        download_status[file_name] = f"downloaded ({byte_count:,} bytes)"
    return download_status


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [column.strip() for column in next(csv.reader(handle))]


def verify_raw_schemas(raw_dir: Path = RAW_DATA_DIR) -> dict[str, dict[str, list[str]]]:
    schema_report: dict[str, dict[str, list[str]]] = {}
    missing_by_file: dict[str, list[str]] = {}
    for file_name, required_columns in REQUIRED_COLUMNS.items():
        header = read_csv_header(raw_file_path(file_name, raw_dir))
        missing_columns = [column for column in required_columns if column not in header]
        extra_columns = [column for column in header if column not in required_columns]
        if missing_columns:
            missing_by_file[file_name] = missing_columns
        schema_report[file_name] = {"columns": header, "extra_columns": extra_columns}
    if missing_by_file:
        raise RawSchemaError(f"Required columns missing from raw CSVs: {missing_by_file}")
    return schema_report


def count_csv_records(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1
