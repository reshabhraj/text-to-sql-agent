"""Generate the synthetic sample database used by text-to-sql-agent.

Run with:

    python -m db.seed                 # writes data/sample.db
    python -m db.seed --out other.db  # writes somewhere else

Every value comes from Python's random module seeded with SEED, and the
calendar is anchored to a constant instead of the wall clock, so two runs
produce identical table contents. No real people, companies, or data appear.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42

# The only calendar anchor. Activity data spans January to August 2026.
TODAY = date(2026, 9, 1)
DATA_START = date(2026, 1, 1)
DATA_END = TODAY - timedelta(days=1)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = ROOT / "data" / "sample.db"

N_CUSTOMERS = 200
N_CLICKS = 3000
N_ORDERS = 800
ATTRIBUTED_SHARE = 0.6
MAX_DAYS_CLICK_TO_ORDER = 14

TABLE_ORDER = [
    "customers",
    "products",
    "campaigns",
    "ad_clicks",
    "orders",
    "order_items",
    "payments",
]

COUNTRIES = [
    "Italy",
    "Germany",
    "France",
    "Spain",
    "United Kingdom",
    "Netherlands",
    "United States",
    "Canada",
    "Australia",
    "India",
]

FIRST_NAMES = [
    "Alice", "Marco", "Priya", "Chen", "Fatima", "Lukas", "Sofia", "Diego",
    "Aisha", "Noah", "Elena", "Kwame", "Yuki", "Omar", "Greta", "Ravi",
    "Ines", "Tomas", "Leila", "Jonas",
]

LAST_NAMES = [
    "Rossi", "Schmidt", "Patel", "Wang", "Haddad", "Novak", "Garcia", "Okafor",
    "Tanaka", "Silva", "Dubois", "Berg", "Costa", "Nair", "Moreau", "Kowalski",
    "Fischer", "Mensah", "Ali", "Larsen",
]

# 5 categories, 6 products each: 30 products.
PRODUCTS_BY_CATEGORY = {
    "shoes": [
        "Trail Runner", "City Sneaker", "Leather Loafer",
        "Hiking Boot", "Canvas Slip-On", "Track Flat",
    ],
    "apparel": [
        "Merino Sweater", "Denim Jacket", "Linen Shirt",
        "Rain Parka", "Cotton Tee", "Wool Coat",
    ],
    "accessories": [
        "Leather Belt", "Canvas Tote", "Knit Beanie",
        "Silk Scarf", "Steel Watch", "Polarised Sunglasses",
    ],
    "electronics": [
        "Wireless Earbuds", "Bluetooth Speaker", "Fitness Tracker",
        "Power Bank", "Smart Bulb Kit", "Noise Cancelling Headphones",
    ],
    "home": [
        "Ceramic Mug Set", "Scented Candle", "Linen Cushion",
        "Bamboo Cutting Board", "Wool Throw", "Glass Carafe",
    ],
}

# Inclusive integer price range per category. Prices end in .99.
PRICE_RANGES = {
    "shoes": (50, 160),
    "apparel": (20, 200),
    "accessories": (10, 250),
    "electronics": (25, 300),
    "home": (10, 90),
}

# 8 campaigns, 4 per platform, windows spread across January to August 2026.
CAMPAIGNS = [
    ("New Year Kickoff", "google", date(2026, 1, 1), date(2026, 1, 31)),
    ("Winter Clearance", "meta", date(2026, 1, 15), date(2026, 2, 28)),
    ("Spring Launch", "google", date(2026, 3, 1), date(2026, 4, 15)),
    ("Easter Deals", "meta", date(2026, 3, 20), date(2026, 4, 10)),
    ("Summer Preview", "google", date(2026, 5, 1), date(2026, 6, 15)),
    ("Mid-Year Sale", "meta", date(2026, 6, 1), date(2026, 7, 15)),
    ("Back to School", "google", date(2026, 7, 15), date(2026, 8, 31)),
    ("August Flash Sale", "meta", date(2026, 8, 1), date(2026, 8, 31)),
]

LANDING_PAGES = [
    "/",
    "/sale",
    "/new-arrivals",
    "/shoes",
    "/apparel",
    "/accessories",
    "/electronics",
    "/home",
    "/landing/summer",
    "/landing/winter",
]

ORDER_STATUSES = ["paid", "pending", "refunded"]
ORDER_STATUS_WEIGHTS = [75, 10, 15]
PAYMENT_METHODS = ["card", "paypal", "bank_transfer"]

INSERTS = {
    "customers": (
        "INSERT INTO customers (id, name, email, country, created_at) "
        "VALUES (?, ?, ?, ?, ?)"
    ),
    "products": (
        "INSERT INTO products (id, name, category, unit_price) "
        "VALUES (?, ?, ?, ?)"
    ),
    "campaigns": (
        "INSERT INTO campaigns (id, name, platform, start_date, end_date, budget) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    ),
    "ad_clicks": (
        "INSERT INTO ad_clicks (id, campaign_id, session_id, clicked_at, landing_page) "
        "VALUES (?, ?, ?, ?, ?)"
    ),
    "orders": (
        "INSERT INTO orders (id, customer_id, session_id, order_date, status, total_amount) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    ),
    "order_items": (
        "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) "
        "VALUES (?, ?, ?, ?, ?)"
    ),
    "payments": (
        "INSERT INTO payments (id, order_id, amount, method, paid_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    ),
}


# Helpers. Dates and timestamps are stored as ISO text, which is what SQLite
# date functions expect and what PostgreSQL casts without complaint.


def _random_datetime(start: date, end: date) -> datetime:
    """Uniform timestamp between start 00:00:00 and end 23:59:59 inclusive."""
    day = start + timedelta(days=random.randint(0, (end - start).days))
    return datetime.combine(day, datetime.min.time()) + timedelta(
        seconds=random.randint(0, 24 * 3600 - 1)
    )


def _fmt_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _fmt_date(value: date) -> str:
    return value.isoformat()


def _money(value: float) -> float:
    return round(value, 2)


def _session_id() -> str:
    # random.getrandbits is driven by the seeded generator, unlike uuid4.
    return f"sess_{random.getrandbits(64):016x}"


# Row builders. Each returns rows in the column order used by INSERTS.


def build_customers() -> list[tuple]:
    created = [_random_datetime(DATA_START, DATA_END) for _ in range(N_CUSTOMERS)]
    # Guarantee at least one customer exists on the first day of activity so
    # early orders always have someone to belong to.
    created[0] = datetime(2026, 1, 1, 9, 0, 0)
    created.sort()
    rows = []
    for i, created_at in enumerate(created, start=1):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        rows.append((i, f"{first} {last}", email, random.choice(COUNTRIES), _fmt_ts(created_at)))
    return rows


def build_products() -> list[tuple]:
    rows = []
    product_id = 1
    for category, names in PRODUCTS_BY_CATEGORY.items():
        low, high = PRICE_RANGES[category]
        for name in names:
            price = _money(random.randint(low, high) - 0.01)
            rows.append((product_id, name, category, price))
            product_id += 1
    return rows


def build_campaigns() -> list[tuple]:
    rows = []
    for i, (name, platform, start, end) in enumerate(CAMPAIGNS, start=1):
        budget = float(random.randint(50, 500) * 100)
        rows.append((i, name, platform, _fmt_date(start), _fmt_date(end), budget))
    return rows


def build_clicks() -> list[tuple]:
    drafts = []
    seen = set()
    for _ in range(N_CLICKS):
        campaign_index = random.randrange(len(CAMPAIGNS))
        _, _, start, end = CAMPAIGNS[campaign_index]
        clicked_at = _random_datetime(start, end)
        session_id = _session_id()
        while session_id in seen:
            session_id = _session_id()
        seen.add(session_id)
        drafts.append((campaign_index + 1, session_id, _fmt_ts(clicked_at), random.choice(LANDING_PAGES)))
    # Ids follow click time so the table reads like a real event log.
    drafts.sort(key=lambda row: (row[2], row[1]))
    return [(i, *row) for i, row in enumerate(drafts, start=1)]


def build_orders(customers: list[tuple], clicks: list[tuple]) -> list[list]:
    """Return mutable rows; total_amount is filled in by build_order_items."""
    # customers are sorted by created_at, so this list is ascending.
    created_dates = [_parse_ts(row[4]).date() for row in customers]

    n_attributed = round(N_ORDERS * ATTRIBUTED_SHARE)
    drafts: list[tuple[date, str | None]] = []

    # Attributed orders reuse a click's session_id, sampled without
    # replacement, with the order strictly after the click and inside the
    # activity window. A click too close to DATA_END is skipped, not stretched.
    candidates = list(clicks)
    random.shuffle(candidates)
    for click in candidates:
        if len(drafts) == n_attributed:
            break
        click_date = _parse_ts(click[3]).date()
        earliest = click_date + timedelta(days=1)
        if earliest > DATA_END:
            continue
        latest = min(click_date + timedelta(days=MAX_DAYS_CLICK_TO_ORDER), DATA_END)
        order_date = earliest + timedelta(days=random.randint(0, (latest - earliest).days))
        drafts.append((order_date, click[2]))
    if len(drafts) != n_attributed:
        raise RuntimeError("not enough eligible clicks to attribute orders")

    # The rest are genuinely unattributed: session_id is NULL.
    for _ in range(N_ORDERS - n_attributed):
        order_date = DATA_START + timedelta(days=random.randint(0, (DATA_END - DATA_START).days))
        drafts.append((order_date, None))

    drafts.sort(key=lambda draft: (draft[0], draft[1] or ""))

    rows = []
    for i, (order_date, session_id) in enumerate(drafts, start=1):
        eligible = bisect_right(created_dates, order_date)
        customer_id = customers[random.randrange(eligible)][0]
        status = random.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS)[0]
        rows.append([i, customer_id, session_id, _fmt_date(order_date), status, 0.0])
    return rows


def build_order_items(orders: list[list], products: list[tuple]) -> list[tuple]:
    rows = []
    item_id = 1
    for order in orders:
        chosen = random.sample(products, k=random.randint(1, 4))
        total = 0.0
        for product in chosen:
            quantity = random.randint(1, 3)
            unit_price = product[3]
            rows.append((item_id, order[0], product[0], quantity, unit_price))
            total += quantity * unit_price
            item_id += 1
        order[5] = _money(total)
    return rows


def build_payments(orders: list[list]) -> list[tuple]:
    rows = []
    payment_id = 1
    for order in orders:
        if order[4] != "paid":
            continue
        order_date = date.fromisoformat(order[3])
        latest = min(order_date + timedelta(days=2), DATA_END)
        paid_at = _random_datetime(order_date, latest)
        rows.append((payment_id, order[0], order[5], random.choice(PAYMENT_METHODS), _fmt_ts(paid_at), "completed"))
        payment_id += 1
    return rows


def seed(db_path: Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Create the database at db_path from scratch and return row counts."""
    random.seed(SEED)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    customers = build_customers()
    products = build_products()
    campaigns = build_campaigns()
    clicks = build_clicks()
    orders = build_orders(customers, clicks)
    order_items = build_order_items(orders, products)
    payments = build_payments(orders)

    tables = {
        "customers": customers,
        "products": products,
        "campaigns": campaigns,
        "ad_clicks": clicks,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
    }

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        with conn:
            for table in TABLE_ORDER:
                conn.executemany(INSERTS[table], tables[table])
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLE_ORDER
        }
    finally:
        conn.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic sample database.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="where to write the SQLite file (default: data/sample.db)",
    )
    args = parser.parse_args(argv)
    counts = seed(args.out)
    print(f"Seeded {args.out}")
    for table, count in counts.items():
        print(f"  {table:<12} {count:>6}")


if __name__ == "__main__":
    main()
