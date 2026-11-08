from pathlib import Path

import duckdb

from src.data import PROJECT_ROOT, RAW_DATA_DIR, count_csv_records, raw_file_path

DATABASE_PATH: Path = PROJECT_ROOT / "data" / "marketplace.duckdb"
SQL_DIR: Path = PROJECT_ROOT / "sql"
MART_SQL_FILES: tuple[str, ...] = (
    "01_mart_order_fulfillment.sql",
    "02_mart_cohort_retention.sql",
    "03_mart_seller_pareto.sql",
    "04_mart_olist_monthly.sql",
    "05_mart_olist_category.sql",
    "06_mart_olist_state.sql",
    "07_mart_olist_payments.sql",
)
MAX_PLAUSIBLE_BRAZIL_DISTANCE_KM: float = 5000.0
MART_TABLES: tuple[str, ...] = (
    "mart_order_fulfillment",
    "mart_cohort_retention",
    "mart_seller_pareto",
    "mart_olist_monthly",
    "mart_olist_category",
    "mart_olist_state",
    "mart_olist_payments",
)

RAW_TABLE_SOURCES: dict[str, str] = {
    "raw_customers": "olist_customers_dataset.csv",
    "raw_orders": "olist_orders_dataset.csv",
    "raw_order_items": "olist_order_items_dataset.csv",
    "raw_order_payments": "olist_order_payments_dataset.csv",
    "raw_order_reviews": "olist_order_reviews_dataset.csv",
    "raw_products": "olist_products_dataset.csv",
    "raw_sellers": "olist_sellers_dataset.csv",
    "raw_geolocation": "olist_geolocation_dataset.csv",
}

RAW_COLUMN_TYPE_OVERRIDES: dict[str, dict[str, str]] = {
    "raw_customers": {"customer_zip_code_prefix": "INTEGER"},
    "raw_sellers": {"seller_zip_code_prefix": "INTEGER"},
    "raw_geolocation": {
        "geolocation_zip_code_prefix": "INTEGER",
        "geolocation_lat": "DOUBLE",
        "geolocation_lng": "DOUBLE",
    },
    "raw_order_items": {"price": "DOUBLE", "freight_value": "DOUBLE"},
    "raw_order_reviews": {
        "review_score": "INTEGER",
        "review_comment_title": "VARCHAR",
        "review_comment_message": "VARCHAR",
    },
}


class WarehouseIntegrityError(RuntimeError):
    pass


def sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def duckdb_struct_literal(column_types: dict[str, str]) -> str:
    entries = ", ".join(f"{sql_string_literal(name)}: {sql_string_literal(kind)}" for name, kind in column_types.items())
    return "{" + entries + "}"


def build_read_csv_expression(table_name: str, csv_path: Path) -> str:
    options = [
        sql_string_literal(csv_path.as_posix()),
        "header = true",
        "quote = '\"'",
        "escape = '\"'",
        "sample_size = -1",
    ]
    column_types = RAW_COLUMN_TYPE_OVERRIDES.get(table_name)
    if column_types:
        options.append(f"types = {duckdb_struct_literal(column_types)}")
    return "read_csv(" + ", ".join(options) + ")"


def load_raw_tables(connection: duckdb.DuckDBPyConnection, raw_dir: Path = RAW_DATA_DIR) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for table_name, file_name in RAW_TABLE_SOURCES.items():
        read_expression = build_read_csv_expression(table_name, raw_file_path(file_name, raw_dir))
        connection.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {read_expression}")
        row_counts[table_name] = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    return row_counts


def verify_review_parsing(connection: duckdb.DuckDBPyConnection, raw_dir: Path = RAW_DATA_DIR) -> dict[str, int]:
    python_csv_records = count_csv_records(raw_file_path(RAW_TABLE_SOURCES["raw_order_reviews"], raw_dir))
    duckdb_records = connection.execute("SELECT COUNT(*) FROM raw_order_reviews").fetchone()[0]
    if python_csv_records != duckdb_records:
        raise WarehouseIntegrityError(
            f"Review CSV parsed into {duckdb_records} DuckDB rows but {python_csv_records} csv-module records; "
            "multiline quoted comments were split."
        )
    return {"python_csv_module_records": python_csv_records, "duckdb_records": duckdb_records}


def execute_mart_sql(connection: duckdb.DuckDBPyConnection, sql_dir: Path = SQL_DIR) -> dict[str, int]:
    for sql_file in MART_SQL_FILES:
        connection.execute((sql_dir / sql_file).read_text(encoding="utf-8"))
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in MART_TABLES}


def collect_grain_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, float | int]:
    duplicate_order_rows = connection.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM mart_order_fulfillment"
    ).fetchone()[0]
    geolocation_profile = connection.execute(
        """
        SELECT
            COUNT(*) AS raw_rows,
            COUNT(DISTINCT geolocation_zip_code_prefix) AS distinct_prefixes,
            SUM(CASE WHEN geolocation_lat NOT BETWEEN -35.0 AND 5.5
                       OR geolocation_lng NOT BETWEEN -75.0 AND -33.0 THEN 1 ELSE 0 END) AS out_of_brazil_rows
        FROM raw_geolocation
        """
    ).fetchone()
    review_profile = connection.execute(
        """
        SELECT
            SUM(review_count) AS review_rows,
            COUNT(*) AS reviewed_orders,
            COUNT(*) FILTER (WHERE review_count > 1) AS orders_with_multiple_reviews
        FROM (SELECT order_id, COUNT(*) AS review_count FROM raw_order_reviews GROUP BY order_id)
        """
    ).fetchone()
    customer_profile = connection.execute(
        """
        SELECT
            (SELECT COUNT(DISTINCT customer_id) FROM raw_customers) AS distinct_customer_ids,
            (SELECT COUNT(DISTINCT customer_unique_id) FROM raw_customers) AS distinct_customer_unique_ids
        """
    ).fetchone()
    fulfillment_profile = connection.execute(
        """
        SELECT
            COUNT(*) AS delivered_orders,
            AVG(CASE WHEN delivery_distance_km IS NOT NULL THEN 1.0 ELSE 0.0 END) AS distance_coverage,
            AVG(CASE WHEN review_score IS NOT NULL THEN 1.0 ELSE 0.0 END) AS review_coverage,
            AVG(CASE WHEN order_gmv IS NOT NULL THEN 1.0 ELSE 0.0 END) AS item_coverage,
            MAX(delivery_distance_km) AS max_distance_km
        FROM mart_order_fulfillment
        """
    ).fetchone()
    if duplicate_order_rows != 0:
        raise WarehouseIntegrityError(f"mart_order_fulfillment has {duplicate_order_rows} duplicate order_id rows.")
    if fulfillment_profile[4] is not None and fulfillment_profile[4] > MAX_PLAUSIBLE_BRAZIL_DISTANCE_KM:
        raise WarehouseIntegrityError(f"Implausible delivery distance {fulfillment_profile[4]:.0f} km inside Brazil.")
    return {
        "mart_order_fulfillment_duplicate_order_ids": int(duplicate_order_rows),
        "geolocation_raw_rows": int(geolocation_profile[0]),
        "geolocation_distinct_zip_prefixes": int(geolocation_profile[1]),
        "geolocation_out_of_brazil_rows_excluded": int(geolocation_profile[2]),
        "review_rows": int(review_profile[0]),
        "reviewed_orders": int(review_profile[1]),
        "orders_with_multiple_reviews": int(review_profile[2]),
        "distinct_customer_ids": int(customer_profile[0]),
        "distinct_customer_unique_ids": int(customer_profile[1]),
        "delivered_orders_in_mart": int(fulfillment_profile[0]),
        "delivery_distance_coverage_rate": float(fulfillment_profile[1]),
        "review_coverage_rate": float(fulfillment_profile[2]),
        "order_item_coverage_rate": float(fulfillment_profile[3]),
        "max_delivery_distance_km": float(fulfillment_profile[4]),
    }


def build_warehouse(database_path: Path = DATABASE_PATH, raw_dir: Path = RAW_DATA_DIR) -> dict[str, dict]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        raw_row_counts = load_raw_tables(connection, raw_dir)
        review_parsing_check = verify_review_parsing(connection, raw_dir)
        mart_row_counts = execute_mart_sql(connection)
        grain_checks = collect_grain_checks(connection)
        connection.execute("CHECKPOINT")
    return {
        "raw_row_counts": raw_row_counts,
        "review_csv_parsing_check": review_parsing_check,
        "mart_row_counts": mart_row_counts,
        "grain_checks": grain_checks,
    }


def connect_read_only(database_path: Path = DATABASE_PATH) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(database_path), read_only=True)
