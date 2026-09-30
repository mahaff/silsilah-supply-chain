"""Load one region's synthetic CSV files into that region's SQLite file.

Run both regions from the project folder:

    python -m persistence.seed

The command rebuilds data/ksa/war_room.sqlite and data/pakistan/war_room.sqlite.
It never reads the other region's seed folder. It never inserts governance rows.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from domain.evidence import EvidenceKind
from domain.models import OrderStatus, RegionCode, ShipmentStatus, SupplierStatus
from domain.risks import DATASET_AS_OF_DATE
from persistence.connection import RegionConfig, connect, load_region_config
from persistence.schema import SCHEMA_SQL

CHAIN_SCOPED_TABLES = (
    "suppliers",
    "products",
    "warehouses",
    "inventory",
    "purchase_orders",
    "demand_history",
)

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "organizations": ("id", "name", "region_code"),
    "supply_chains": ("id", "organization_id", "name"),
    "suppliers": ("id", "supply_chain_id", "name", "city", "status", "lead_time_days"),
    "products": ("id", "supply_chain_id", "sku", "name", "category", "unit"),
    "warehouses": ("id", "supply_chain_id", "name", "city"),
    "inventory": (
        "id",
        "supply_chain_id",
        "warehouse_id",
        "product_id",
        "on_hand",
        "reorder_point",
    ),
    "purchase_orders": (
        "id",
        "supply_chain_id",
        "supplier_id",
        "warehouse_id",
        "status",
        "ordered_on",
        "expected_on",
    ),
    "purchase_order_lines": (
        "id",
        "purchase_order_id",
        "product_id",
        "quantity",
        "unit_cost_minor",
        "currency",
    ),
    "shipments": (
        "id",
        "purchase_order_id",
        "origin",
        "destination",
        "status",
        "departed_on",
        "eta",
        "arrived_on",
    ),
    "demand_history": (
        "id",
        "supply_chain_id",
        "warehouse_id",
        "product_id",
        "period_start",
        "period_end",
        "quantity_issued",
    ),
}


def seed_region(region_code: str, database_path: Path | None = None) -> Path:
    """Rebuild one regional database from its own seed folder.

    Pass database_path in tests so they do not write the shared data/ files.
    """
    config = load_region_config(region_code)
    target = database_path if database_path is not None else config.database_path
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = _read_seed_frames(config)
    _validate_frames(config, frames)

    # Remove the previous file so a rebuild cannot leave old rows behind.
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(target) + suffix) if suffix else target
        if stale.exists():
            stale.unlink()

    connection = connect(target)
    try:
        connection.executescript(SCHEMA_SQL)
        _insert_frames(connection, config, frames)
        problems = connection.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise ValueError(f"Foreign key check failed for {config.region_code}: {problems}")
        governance_count = connection.execute(
            "SELECT COUNT(*) AS count FROM governance_references"
        ).fetchone()["count"]
        if governance_count != 0:
            raise ValueError("Seeding must leave governance_references empty.")
        connection.commit()
    except Exception:
        connection.close()
        if target.exists():
            target.unlink()
        raise
    connection.close()
    return target


def _read_seed_frames(config: RegionConfig) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for name, columns in REQUIRED_COLUMNS.items():
        path = config.seed_dir / f"{name}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Missing seed file: {path}")
        # utf-8-sig drops a byte-order mark if the file was saved by Excel.
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        frame.columns = [column.strip() for column in frame.columns]
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
        frame = frame.loc[:, list(columns)]
        for column in frame.columns:
            frame[column] = frame[column].str.strip()
        if frame.empty:
            raise ValueError(f"{path.name} has no data rows.")
        frames[name] = frame
    return frames


def _validate_frames(config: RegionConfig, frames: dict[str, pd.DataFrame]) -> None:
    organizations = frames["organizations"]
    chains = frames["supply_chains"]
    if len(organizations) != 1 or len(chains) != 1:
        raise ValueError(
            f"{config.display_name} must seed exactly one organization and one supply chain."
        )

    organization = organizations.iloc[0]
    chain = chains.iloc[0]
    if organization["region_code"] != config.region_code:
        raise ValueError(
            "organizations.csv region_code does not match "
            f"{config.region_code}."
        )
    if chain["organization_id"] != organization["id"]:
        raise ValueError("The supply chain organization_id does not match the organization.")

    chain_id = chain["id"]
    for name in CHAIN_SCOPED_TABLES:
        foreign = frames[name]["supply_chain_id"]
        if not foreign.eq(chain_id).all():
            raise ValueError(f"Every {name}.csv row must use supply chain {chain_id}.")

    _require_unique(organizations, "id", "organizations.csv")
    _require_unique(chains, "id", "supply_chains.csv")
    _require_unique(frames["suppliers"], "id", "suppliers.csv")
    _require_unique(frames["products"], "id", "products.csv")
    _require_unique(frames["products"], "sku", "products.csv")
    _require_unique(frames["warehouses"], "id", "warehouses.csv")
    _require_unique(frames["inventory"], "id", "inventory.csv")
    _require_unique(frames["purchase_orders"], "id", "purchase_orders.csv")
    _require_unique(frames["purchase_order_lines"], "id", "purchase_order_lines.csv")
    _require_unique(frames["shipments"], "id", "shipments.csv")
    _require_unique(frames["demand_history"], "id", "demand_history.csv")

    inventory_key = frames["inventory"]["warehouse_id"] + "|" + frames["inventory"]["product_id"]
    if inventory_key.duplicated().any():
        raise ValueError("inventory.csv repeats a warehouse and product pair.")

    _require_members(
        frames["suppliers"]["status"],
        {status.value for status in SupplierStatus},
        "suppliers.csv status",
    )
    _require_members(
        frames["purchase_orders"]["status"],
        {status.value for status in OrderStatus},
        "purchase_orders.csv status",
    )
    _require_members(
        frames["shipments"]["status"],
        {status.value for status in ShipmentStatus},
        "shipments.csv status",
    )

    supplier_ids = set(frames["suppliers"]["id"])
    product_ids = set(frames["products"]["id"])
    warehouse_ids = set(frames["warehouses"]["id"])
    order_ids = set(frames["purchase_orders"]["id"])
    _require_known(frames["inventory"]["warehouse_id"], warehouse_ids, "inventory warehouse_id")
    _require_known(frames["inventory"]["product_id"], product_ids, "inventory product_id")
    _require_known(frames["purchase_orders"]["supplier_id"], supplier_ids, "purchase order supplier_id")
    _require_known(frames["purchase_orders"]["warehouse_id"], warehouse_ids, "purchase order warehouse_id")
    _require_known(frames["purchase_order_lines"]["purchase_order_id"], order_ids, "order line purchase_order_id")
    _require_known(frames["purchase_order_lines"]["product_id"], product_ids, "order line product_id")
    _require_known(frames["shipments"]["purchase_order_id"], order_ids, "shipment purchase_order_id")
    _require_known(frames["demand_history"]["warehouse_id"], warehouse_ids, "demand warehouse_id")
    _require_known(frames["demand_history"]["product_id"], product_ids, "demand product_id")

    if not frames["purchase_order_lines"]["currency"].eq(config.currency).all():
        raise ValueError(
            f"Every order line currency must be {config.currency} for {config.display_name}."
        )

    for column in ("on_hand", "reorder_point", "lead_time_days"):
        table = "inventory" if column != "lead_time_days" else "suppliers"
        _require_non_negative(frames[table][column], f"{table}.{column}")
    _require_positive(frames["purchase_order_lines"]["quantity"], "quantity")
    _require_positive(frames["purchase_order_lines"]["unit_cost_minor"], "unit_cost_minor")
    _require_positive(frames["demand_history"]["quantity_issued"], "quantity_issued")
    _validate_demand_periods(frames["demand_history"])

    for _, order in frames["purchase_orders"].iterrows():
        ordered = _parse_date(order["ordered_on"], f"{order['id']} ordered_on")
        expected = _parse_date(order["expected_on"], f"{order['id']} expected_on")
        if expected < ordered:
            raise ValueError(f"{order['id']} expected_on is earlier than ordered_on.")

    for _, shipment in frames["shipments"].iterrows():
        _validate_shipment_dates(shipment)


def _validate_demand_periods(frame: pd.DataFrame) -> None:
    """Issue periods must be real dates, in order, and not overlapping."""
    seen: dict[str, list[tuple[date, date]]] = {}
    for _, period in frame.iterrows():
        label = str(period["id"])
        start = _parse_date(str(period["period_start"]), f"{label} period_start")
        end = _parse_date(str(period["period_end"]), f"{label} period_end")
        if end < start:
            raise ValueError(f"{label} period_end is earlier than period_start.")
        if end > DATASET_AS_OF_DATE:
            raise ValueError(
                f"{label} ends after the synthetic dataset as-of date {DATASET_AS_OF_DATE.isoformat()}."
            )
        key = f"{period['warehouse_id']}|{period['product_id']}"
        seen.setdefault(key, []).append((start, end))
    for key, ranges in seen.items():
        ranges.sort()
        previous_end: date | None = None
        for start, end in ranges:
            if previous_end is not None and start <= previous_end:
                raise ValueError(f"Demand periods overlap for {key}.")
            previous_end = end


def _validate_shipment_dates(shipment: pd.Series) -> None:
    """Keep shipment dates consistent with the status token."""
    label = str(shipment["id"])
    status = str(shipment["status"])
    departed = str(shipment["departed_on"])
    arrived = str(shipment["arrived_on"])
    _parse_date(str(shipment["eta"]), f"{label} eta")

    if status == ShipmentStatus.PLANNED.value:
        if departed or arrived:
            raise ValueError(f"{label} is planned, so departure and arrival must be empty.")
        return
    if not departed:
        raise ValueError(f"{label} has left or should have left, so departed_on is required.")
    _parse_date(departed, f"{label} departed_on")
    if status == ShipmentStatus.DELIVERED.value:
        if not arrived:
            raise ValueError(f"{label} is delivered, so arrived_on is required.")
        _parse_date(arrived, f"{label} arrived_on")
        return
    if arrived:
        raise ValueError(f"{label} is not delivered, so arrived_on must be empty.")


def _insert_frames(
    connection: sqlite3.Connection,
    config: RegionConfig,
    frames: dict[str, pd.DataFrame],
) -> None:
    organization = frames["organizations"].iloc[0]
    chain = frames["supply_chains"].iloc[0]
    connection.execute(
        "INSERT INTO organizations (id, name, region_code) VALUES (?, ?, ?)",
        (organization["id"], organization["name"], organization["region_code"]),
    )
    connection.execute(
        "INSERT INTO supply_chains (id, organization_id, name) VALUES (?, ?, ?)",
        (chain["id"], chain["organization_id"], chain["name"]),
    )
    _executemany(
        connection,
        """
        INSERT INTO suppliers (id, supply_chain_id, name, city, status, lead_time_days)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        frames["suppliers"],
        ("id", "supply_chain_id", "name", "city", "status", "lead_time_days"),
        integers={"lead_time_days"},
    )
    _executemany(
        connection,
        """
        INSERT INTO products (id, supply_chain_id, sku, name, category, unit)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        frames["products"],
        ("id", "supply_chain_id", "sku", "name", "category", "unit"),
    )
    _executemany(
        connection,
        """
        INSERT INTO warehouses (id, supply_chain_id, name, city)
        VALUES (?, ?, ?, ?)
        """,
        frames["warehouses"],
        ("id", "supply_chain_id", "name", "city"),
    )
    _executemany(
        connection,
        """
        INSERT INTO inventory (
            id, supply_chain_id, warehouse_id, product_id, on_hand, reorder_point
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        frames["inventory"],
        ("id", "supply_chain_id", "warehouse_id", "product_id", "on_hand", "reorder_point"),
        integers={"on_hand", "reorder_point"},
    )
    _executemany(
        connection,
        """
        INSERT INTO purchase_orders (
            id, supply_chain_id, supplier_id, warehouse_id, status, ordered_on, expected_on
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        frames["purchase_orders"],
        (
            "id",
            "supply_chain_id",
            "supplier_id",
            "warehouse_id",
            "status",
            "ordered_on",
            "expected_on",
        ),
    )
    _executemany(
        connection,
        """
        INSERT INTO purchase_order_lines (
            id, purchase_order_id, product_id, quantity, unit_cost_minor, currency
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        frames["purchase_order_lines"],
        ("id", "purchase_order_id", "product_id", "quantity", "unit_cost_minor", "currency"),
        integers={"quantity", "unit_cost_minor"},
    )
    _executemany(
        connection,
        """
        INSERT INTO shipments (
            id, purchase_order_id, origin, destination, status, departed_on, eta, arrived_on
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        frames["shipments"],
        (
            "id",
            "purchase_order_id",
            "origin",
            "destination",
            "status",
            "departed_on",
            "eta",
            "arrived_on",
        ),
        empty_as_null={"departed_on", "arrived_on"},
    )
    _executemany(
        connection,
        """
        INSERT INTO demand_history (
            id, supply_chain_id, warehouse_id, product_id,
            period_start, period_end, quantity_issued
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        frames["demand_history"],
        (
            "id",
            "supply_chain_id",
            "warehouse_id",
            "product_id",
            "period_start",
            "period_end",
            "quantity_issued",
        ),
        integers={"quantity_issued"},
    )

    seeded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta = {
        "region_code": config.region_code,
        "display_name": config.display_name,
        "currency": config.currency,
        "minor_unit_name": config.minor_unit_name,
        "timezone": config.timezone,
        "synthetic": "true",
        "dataset_label": "synthetic",
        "organization_id": str(organization["id"]),
        "supply_chain_id": str(chain["id"]),
        "seeded_at": seeded_at,
        # Fixed dataset clock for overdue checks. Not the computer's current date.
        "dataset_as_of": DATASET_AS_OF_DATE.isoformat(),
    }
    connection.executemany(
        "INSERT INTO app_meta (key, value) VALUES (?, ?)",
        list(meta.items()),
    )
    connection.execute(
        """
        INSERT INTO audit_events (occurred_at, actor, action, evidence_kind, summary)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            seeded_at,
            "system",
            "seed_synthetic_dataset",
            EvidenceKind.DATABASE_FACT.value,
            (
                f"Loaded the synthetic dataset for {config.display_name}. "
                "This is not live supply-chain data."
            ),
        ),
    )


def _executemany(
    connection: sqlite3.Connection,
    sql: str,
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    integers: set[str] | None = None,
    empty_as_null: set[str] | None = None,
) -> None:
    integer_columns = integers or set()
    null_columns = empty_as_null or set()
    rows: list[tuple[object, ...]] = []
    for _, record in frame.iterrows():
        values: list[object] = []
        for column in columns:
            text = str(record[column])
            if column in null_columns and text == "":
                values.append(None)
            elif column in integer_columns:
                values.append(int(text))
            else:
                values.append(text)
        rows.append(tuple(values))
    connection.executemany(sql, rows)


def _require_unique(frame: pd.DataFrame, column: str, filename: str) -> None:
    duplicates = frame.loc[frame[column].duplicated(), column].tolist()
    if duplicates:
        raise ValueError(f"{filename} has duplicate {column} values: {duplicates}")


def _require_members(series: pd.Series, allowed: set[str], label: str) -> None:
    unknown = sorted(set(series) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown values: {unknown}")


def _require_known(series: pd.Series, known: set[str], label: str) -> None:
    missing = sorted(set(series) - known)
    if missing:
        raise ValueError(f"{label} points at unknown ids: {missing}")


def _require_non_negative(series: pd.Series, label: str) -> None:
    for value in series:
        number = _parse_int(str(value), label)
        if number < 0:
            raise ValueError(f"{label} cannot be negative.")


def _require_positive(series: pd.Series, label: str) -> None:
    for value in series:
        number = _parse_int(str(value), label)
        if number <= 0:
            raise ValueError(f"{label} must be greater than zero.")


def _parse_int(value: str, label: str) -> int:
    if not value.isdigit():
        raise ValueError(f"{label} must be a whole number, got {value!r}.")
    return int(value)


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a YYYY-MM-DD date, got {value!r}.") from exc


def main() -> None:
    for region_code in (RegionCode.KSA.value, RegionCode.PAKISTAN.value):
        path = seed_region(region_code)
        print(f"Seeded {region_code}: {path}")


if __name__ == "__main__":
    main()
