import argparse
import sys
from pathlib import Path

import duckdb

from mieru.olist.warehouse import REQUIRED_TABLES

RUNTIME_RAW_TABLES: tuple[str, ...] = ("raw_orders", "raw_order_items", "raw_order_payments", "raw_products")


def build_runtime_database(source: Path, target: Path) -> dict[str, int]:
    tables = (*REQUIRED_TABLES, *RUNTIME_RAW_TABLES)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    connection = duckdb.connect(str(target))
    try:
        quoted_source = str(source.resolve()).replace("'", "''")
        connection.execute(f"ATTACH '{quoted_source}' AS source (READ_ONLY)")
        counts: dict[str, int] = {}
        for table in tables:
            connection.execute(f"CREATE TABLE {table} AS SELECT * FROM source.main.{table}")
            copied = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            original = connection.execute(f"SELECT COUNT(*) FROM source.main.{table}").fetchone()[0]
            if copied != original:
                raise RuntimeError(f"{table}: copied {copied} rows but the source has {original}")
            counts[table] = copied
        connection.execute("DETACH source")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the tables the MIERU web app reads into a smaller read-only database.")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args()
    counts = build_runtime_database(arguments.source, arguments.target)
    for table, rows in counts.items():
        print(f"{table}\t{rows}")
    print(f"{arguments.target}\t{arguments.target.stat().st_size / 1_048_576:.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
