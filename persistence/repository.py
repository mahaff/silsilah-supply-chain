"""Read one regional database into domain objects.

Every operational query filters on the single supply chain id. MVP 1 has
only one chain, and the filter is what will keep a second chain separate later.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from domain.models import (
    AuditEvent,
    InventoryRow,
    Organization,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRow,
    RegionScope,
    Shipment,
    Supplier,
    SupplyChain,
    Warehouse,
)
from persistence.connection import connect, load_region_config


class RegionRepository:
    def __init__(self, region_code: str, database_path: Path | None = None) -> None:
        self.config = load_region_config(region_code)
        self.database_path = (
            database_path if database_path is not None else self.config.database_path
        )

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Open the regional file, check it, and always close it."""
        if not self.database_path.is_file():
            raise FileNotFoundError(
                "No database for "
                f"{self.config.display_name} at {self.database_path}. "
                "Run: python -m persistence.seed"
            )
        connection = connect(self.database_path)
        try:
            self._require_matching_region(connection)
            yield connection
        finally:
            connection.close()

    def _require_matching_region(self, connection: sqlite3.Connection) -> None:
        """Stop if this file was built for the other region."""
        row = connection.execute(
            "SELECT value FROM app_meta WHERE key = 'region_code'"
        ).fetchone()
        stored = None if row is None else row["value"]
        if stored != self.config.region_code:
            raise ValueError(
                "This database file does not match the selected region "
                f"({self.config.region_code}). Refusing to show mixed regional data."
            )

    def load_scope(self) -> RegionScope:
        """Return the one organization and one supply chain stored in this file."""
        with self._session() as connection:
            organizations = [
                Organization(
                    id=row["id"],
                    name=row["name"],
                    region_code=row["region_code"],
                )
                for row in connection.execute(
                    "SELECT id, name, region_code FROM organizations ORDER BY id"
                )
            ]
            supply_chains = [
                SupplyChain(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    name=row["name"],
                )
                for row in connection.execute(
                    "SELECT id, organization_id, name FROM supply_chains ORDER BY id"
                )
            ]
            meta = {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM app_meta")
            }

        if len(organizations) != 1 or len(supply_chains) != 1:
            raise ValueError(
                "MVP 1 expects exactly one organization and one supply chain "
                "in each regional database."
            )
        if supply_chains[0].organization_id != organizations[0].id:
            raise ValueError(
                "The supply chain does not belong to the organization in this database."
            )
        return RegionScope(
            organization=organizations[0],
            supply_chain=supply_chains[0],
            display_name=meta.get("display_name", self.config.display_name),
            currency=meta.get("currency", self.config.currency),
            timezone=meta.get("timezone", self.config.timezone),
        )

    def list_suppliers(self, supply_chain_id: str) -> list[Supplier]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, supply_chain_id, name, city, status, lead_time_days
                FROM suppliers
                WHERE supply_chain_id = ?
                ORDER BY name
                """,
                (supply_chain_id,),
            ).fetchall()
        return [Supplier.model_validate(dict(row)) for row in rows]

    def list_products(self, supply_chain_id: str) -> list[Product]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, supply_chain_id, sku, name, category, unit
                FROM products
                WHERE supply_chain_id = ?
                ORDER BY sku
                """,
                (supply_chain_id,),
            ).fetchall()
        return [Product.model_validate(dict(row)) for row in rows]

    def list_warehouses(self, supply_chain_id: str) -> list[Warehouse]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, supply_chain_id, name, city
                FROM warehouses
                WHERE supply_chain_id = ?
                ORDER BY name
                """,
                (supply_chain_id,),
            ).fetchall()
        return [Warehouse.model_validate(dict(row)) for row in rows]

    def list_inventory(self, supply_chain_id: str) -> list[InventoryRow]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT
                    i.id,
                    i.supply_chain_id,
                    w.name AS warehouse_name,
                    p.sku,
                    p.name AS product_name,
                    i.on_hand,
                    i.reorder_point
                FROM inventory AS i
                JOIN warehouses AS w ON w.id = i.warehouse_id
                JOIN products AS p ON p.id = i.product_id
                WHERE i.supply_chain_id = ?
                ORDER BY w.name, p.sku
                """,
                (supply_chain_id,),
            ).fetchall()
        return [InventoryRow.model_validate(dict(row)) for row in rows]

    def list_purchase_orders(self, supply_chain_id: str) -> list[PurchaseOrder]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, supply_chain_id, supplier_id, warehouse_id,
                       status, ordered_on, expected_on
                FROM purchase_orders
                WHERE supply_chain_id = ?
                ORDER BY ordered_on, id
                """,
                (supply_chain_id,),
            ).fetchall()
        return [PurchaseOrder.model_validate(dict(row)) for row in rows]

    def list_purchase_order_rows(self, supply_chain_id: str) -> list[PurchaseOrderRow]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT
                    po.id,
                    po.supply_chain_id,
                    s.name AS supplier_name,
                    w.name AS warehouse_name,
                    po.status,
                    po.ordered_on,
                    po.expected_on
                FROM purchase_orders AS po
                JOIN suppliers AS s ON s.id = po.supplier_id
                JOIN warehouses AS w ON w.id = po.warehouse_id
                WHERE po.supply_chain_id = ?
                ORDER BY po.ordered_on, po.id
                """,
                (supply_chain_id,),
            ).fetchall()
        return [PurchaseOrderRow.model_validate(dict(row)) for row in rows]

    def list_purchase_order_lines(self, supply_chain_id: str) -> list[PurchaseOrderLine]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT
                    line.id,
                    line.purchase_order_id,
                    line.product_id,
                    line.quantity,
                    line.unit_cost_minor,
                    line.currency
                FROM purchase_order_lines AS line
                JOIN purchase_orders AS po ON po.id = line.purchase_order_id
                WHERE po.supply_chain_id = ?
                ORDER BY line.id
                """,
                (supply_chain_id,),
            ).fetchall()
        return [PurchaseOrderLine.model_validate(dict(row)) for row in rows]

    def list_shipments(self, supply_chain_id: str) -> list[Shipment]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.purchase_order_id,
                    s.origin,
                    s.destination,
                    s.status,
                    s.departed_on,
                    s.eta,
                    s.arrived_on
                FROM shipments AS s
                JOIN purchase_orders AS po ON po.id = s.purchase_order_id
                WHERE po.supply_chain_id = ?
                ORDER BY s.id
                """,
                (supply_chain_id,),
            ).fetchall()
        return [Shipment.model_validate(dict(row)) for row in rows]

    def governance_reference_count(self) -> int:
        with self._session() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM governance_references"
            ).fetchone()
        return int(row["count"])

    def latest_audit_event(self) -> AuditEvent | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT id, occurred_at, actor, action, evidence_kind, summary
                FROM audit_events
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return AuditEvent.model_validate(dict(row))
