import csv
import datetime as dt
from pathlib import Path

import numpy as np

OUTPUT_PATH: Path = Path(__file__).resolve().parent.parent / "frontend" / "public" / "samples" / "mieru-sample-retail-orders-synthetic.csv"
RANDOM_SEED: int = 7
ORDER_COUNT: int = 1400
START_DATE: dt.date = dt.date(2024, 1, 1)
END_DATE: dt.date = dt.date(2025, 6, 30)
PRODUCTS: tuple[tuple[str, str, int, int], ...] = (
    ("Wireless Earbuds", "Electronics", 7980, 4200),
    ("Smart Watch", "Electronics", 19800, 11800),
    ("USB-C Charger", "Electronics", 2980, 1300),
    ("Green Tea Set", "Food & Drink", 3240, 1500),
    ("Single-Origin Coffee", "Food & Drink", 1980, 820),
    ("Matcha Kit", "Food & Drink", 4580, 2100),
    ("Linen Shirt", "Apparel", 5900, 2400),
    ("Running Shoes", "Apparel", 12800, 6900),
    ("Wool Scarf", "Apparel", 3980, 1600),
    ("Ceramic Mug", "Home", 1650, 540),
    ("Cast Iron Pan", "Home", 8900, 4300),
    ("Desk Lamp", "Home", 6480, 3100),
)
REGIONS: tuple[tuple[str, float], ...] = (
    ("Tokyo", 0.34), ("Osaka", 0.17), ("Kanagawa", 0.14), ("Aichi", 0.10), ("Fukuoka", 0.09), ("Hokkaido", 0.08), ("Kyoto", 0.08),
)
CHANNELS: tuple[tuple[str, float], ...] = (("Online Store", 0.55), ("Marketplace", 0.30), ("Retail Shop", 0.15))
MONTH_SEASONALITY: dict[int, float] = {1: 0.85, 2: 0.75, 3: 0.95, 4: 0.95, 5: 1.0, 6: 0.95, 7: 1.05, 8: 1.0, 9: 0.95, 10: 1.05, 11: 1.25, 12: 1.6}
HEADER: tuple[str, ...] = (
    "Order ID", "Line No", "Order Date", "Customer ID", "Product", "Category", "Region", "Channel",
    "Quantity", "Unit Price", "Discount", "Unit Cost", "Status",
)


def yen(value: float) -> str:
    return f"¥{int(round(value)):,}"


def pick(generator: np.random.Generator, options: tuple[tuple[str, float], ...]) -> str:
    labels = [label for label, _weight in options]
    weights = np.array([weight for _label, weight in options])
    return str(generator.choice(labels, p=weights / weights.sum()))


def order_dates(generator: np.random.Generator) -> list[dt.date]:
    days = (END_DATE - START_DATE).days + 1
    all_days = [START_DATE + dt.timedelta(days=offset) for offset in range(days)]
    growth = np.linspace(0.8, 1.25, days)
    weights = np.array([MONTH_SEASONALITY[day.month] for day in all_days]) * growth
    chosen = generator.choice(days, size=ORDER_COUNT, p=weights / weights.sum())
    return sorted(all_days[index] for index in chosen)


def build_rows(generator: np.random.Generator) -> list[list[str]]:
    customers = [f"CUST-{number:04d}" for number in range(1, 521)]
    customer_weights = generator.pareto(1.4, size=len(customers)) + 1
    customer_weights = customer_weights / customer_weights.sum()
    rows: list[list[str]] = []
    for order_number, order_date in enumerate(order_dates(generator), start=1):
        order_id = f"ORD-{10000 + order_number}"
        customer = str(generator.choice(customers, p=customer_weights))
        region = pick(generator, REGIONS)
        channel = pick(generator, CHANNELS)
        line_count = int(generator.choice([1, 1, 1, 2, 2, 3]))
        status = "Delivered" if order_date < dt.date(2025, 6, 20) else "Shipped"
        if generator.random() < 0.012:
            status = "Cancelled"
        for line_number in range(1, line_count + 1):
            name, category, price, cost = PRODUCTS[int(generator.integers(0, len(PRODUCTS)))]
            quantity = int(generator.choice([1, 1, 1, 2, 2, 3, 4]))
            discount = int(generator.choice([0, 0, 0, 0, 200, 500, 1000])) if price > 3000 else 0
            rows.append([
                order_id, str(line_number), order_date.isoformat(), customer, name, category, region, channel,
                str(quantity), yen(price), yen(discount), yen(cost), status,
            ])
    return rows


def inject_quality_issues(generator: np.random.Generator, rows: list[list[str]]) -> list[list[str]]:
    result = [list(row) for row in rows]
    for index in generator.choice(len(result), size=10, replace=False):
        returned = list(result[int(index)])
        returned[1] = str(int(returned[1]) + 10)
        returned[8] = str(-abs(int(returned[8])))
        returned[10] = yen(0)
        returned[12] = "Returned"
        result.append(returned)
    for index in generator.choice(len(result), size=8, replace=False):
        result.append(list(result[int(index)]))
    for index in generator.choice(len(result), size=4, replace=False):
        result[int(index)][9] = "N/A"
    for index in generator.choice(len(result), size=5, replace=False):
        result[int(index)][2] = ""
    for index in generator.choice(len(result), size=25, replace=False):
        result[int(index)][5] = result[int(index)][5].lower() + " "
    for index in generator.choice(len(result), size=6, replace=False):
        result[int(index)][6] = " " + result[int(index)][6].upper()
    result.sort(key=lambda row: (row[0], int(row[1]) if row[1].lstrip("-").isdigit() else 0))
    blank_positions = sorted(generator.choice(len(result), size=2, replace=False), reverse=True)
    for position in blank_positions:
        result.insert(int(position), [""] * len(HEADER))
    return result


def main() -> None:
    generator = np.random.default_rng(RANDOM_SEED)
    rows = inject_quality_issues(generator, build_rows(generator))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
