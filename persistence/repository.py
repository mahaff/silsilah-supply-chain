"""Read one regional database into domain objects.

Every operational query filters on the single supply chain id. MVP 1 has
only one chain, and the filter is what will keep a second chain separate later.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from domain.evidence import EvidenceKind
from domain.models import (
    AuditEvent,
    DemandPeriod,
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
from domain.risks import (
    DATASET_AS_OF_DATE,
    Risk,
    RiskStatus,
    StoredReview,
    SupplierIndicator,
    detect_risks,
    reconcile_reviews,
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
                    i.warehouse_id,
                    i.product_id,
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
                SELECT id, occurred_at, actor, action, evidence_kind, summary,
                       risk_id, rule_id
                FROM audit_events
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return AuditEvent.model_validate(dict(row))

    def dataset_as_of(self) -> str:
        """Return the synthetic dataset date, never the computer clock."""
        with self._session() as connection:
            row = connection.execute(
                "SELECT value FROM app_meta WHERE key = 'dataset_as_of'"
            ).fetchone()
        stored = None if row is None else row["value"]
        expected = DATASET_AS_OF_DATE.isoformat()
        if stored != expected:
            raise ValueError(
                "This database has no matching synthetic dataset as-of date "
                f"({expected}). Reseed with: python -m persistence.seed. "
                "Overdue checks do not use today's date."
            )
        return stored

    def list_demand(self, supply_chain_id: str) -> list[DemandPeriod]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, supply_chain_id, warehouse_id, product_id,
                       period_start, period_end, quantity_issued
                FROM demand_history
                WHERE supply_chain_id = ?
                ORDER BY id
                """,
                (supply_chain_id,),
            ).fetchall()
        return [DemandPeriod.model_validate(dict(row)) for row in rows]

    def list_reviews(self) -> dict[str, StoredReview]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT risk_id, status, evidence_fingerprint, actor, updated_at,
                       re_review_required, re_review_note
                FROM risk_reviews
                ORDER BY risk_id
                """
            ).fetchall()
        reviews: dict[str, StoredReview] = {}
        for row in rows:
            review = StoredReview(
                risk_id=row["risk_id"],
                status=row["status"],
                evidence_fingerprint=row["evidence_fingerprint"],
                actor=row["actor"],
                updated_at=row["updated_at"],
                re_review_required=bool(row["re_review_required"]),
                re_review_note=row["re_review_note"],
            )
            reviews[review.risk_id] = review
        return reviews

    def list_audit_events(self) -> list[AuditEvent]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, occurred_at, actor, action, evidence_kind, summary,
                       risk_id, rule_id
                FROM audit_events
                ORDER BY id
                """
            ).fetchall()
        return [AuditEvent.model_validate(dict(row)) for row in rows]

    def detected_inputs(self) -> tuple[str, list[Risk], list[SupplierIndicator]]:
        """Load this region's rows and run the deterministic rules."""
        scope = self.load_scope()
        as_of = self.dataset_as_of()
        chain_id = scope.supply_chain.id
        risks, indicators = detect_risks(
            region_code=self.config.region_code,
            inventory=self.list_inventory(chain_id),
            periods=self.list_demand(chain_id),
            shipments=self.list_shipments(chain_id),
            orders=self.list_purchase_orders(chain_id),
            suppliers=self.list_suppliers(chain_id),
            as_of=DATASET_AS_OF_DATE,
        )
        if as_of != DATASET_AS_OF_DATE.isoformat():
            raise ValueError("Dataset as-of date mismatch.")
        return scope.display_name, risks, indicators

    def load_risks(self, *, now: str) -> tuple[list[Risk], list[SupplierIndicator]]:
        """Recalculate risks and keep a review only when its evidence still matches."""
        _display_name, risks, indicators = self.detected_inputs()
        reconciled, updates = reconcile_reviews(risks, self.list_reviews())
        if updates:
            self._write_review_updates(updates, now=now)
        return reconciled, indicators

    def set_risk_status(self, risk_id: str, status: str, *, now: str) -> Risk:
        """Record a local user's review. Evidence rows are not deleted."""
        allowed = {RiskStatus.OPEN, RiskStatus.REVIEWED, RiskStatus.RESOLVED}
        if status not in allowed:
            raise ValueError("Status must be open, reviewed, or resolved.")
        new_status = status
        _display_name, risks, _indicators = self.detected_inputs()
        reconciled, updates = reconcile_reviews(risks, self.list_reviews())
        if updates:
            self._write_review_updates(updates, now=now)
        match = next((risk for risk in reconciled if risk.id == risk_id), None)
        if match is None:
            raise ValueError("That risk is not produced by this region's current rules.")
        if match.status == new_status and match.re_review_note == "":
            raise ValueError(f"This risk is already marked {new_status}.")
        self._save_review(
            risk=match,
            status=new_status,
            now=now,
            actor="local_user",
            re_review_required=False,
            re_review_note="",
        )
        self._insert_audit(
            now=now,
            actor="local_user",
            action="risk_status_changed",
            evidence_kind=EvidenceKind.HUMAN_DECISION.value,
            summary=(
                f"Marked {match.id} as {new_status}. "
                f"Rule {match.rule_id}. Evidence was not deleted."
            ),
            risk_id=match.id,
            rule_id=match.rule_id,
        )
        match.status = new_status
        match.re_review_note = ""
        return match

    def _write_review_updates(self, updates: list, *, now: str) -> None:
        for update in updates:
            self._save_review(
                risk_id=update.risk_id,
                fingerprint=update.evidence_fingerprint,
                status=update.status,
                now=now,
                actor="system",
                re_review_required=update.re_review_required,
                re_review_note=update.re_review_note,
            )
            if not update.write_audit:
                continue
            self._insert_audit(
                now=now,
                actor="system",
                action="risk_reopened_for_rereview",
                evidence_kind=EvidenceKind.DETERMINISTIC_RULE.value,
                summary=(
                    f"Reopened {update.risk_id} for re-review. "
                    f"Previous status was {update.previous_status}. "
                    "The evidence no longer matches the saved review."
                ),
                risk_id=update.risk_id,
                rule_id=update.rule_id,
            )

    def _save_review(
        self,
        *,
        risk: Risk | None = None,
        risk_id: str | None = None,
        fingerprint: str | None = None,
        status: str,
        now: str,
        actor: str,
        re_review_required: bool,
        re_review_note: str,
    ) -> None:
        stored_id = risk.id if risk is not None else risk_id
        stored_fingerprint = risk.evidence_fingerprint if risk is not None else fingerprint
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO risk_reviews (
                    risk_id, status, evidence_fingerprint, actor, updated_at,
                    re_review_required, re_review_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(risk_id) DO UPDATE SET
                    status = excluded.status,
                    evidence_fingerprint = excluded.evidence_fingerprint,
                    actor = excluded.actor,
                    updated_at = excluded.updated_at,
                    re_review_required = excluded.re_review_required,
                    re_review_note = excluded.re_review_note
                """,
                (
                    stored_id,
                    status,
                    stored_fingerprint,
                    actor,
                    now,
                    1 if re_review_required else 0,
                    re_review_note,
                ),
            )
            connection.commit()

    def _insert_audit(
        self,
        *,
        now: str,
        actor: str,
        action: str,
        evidence_kind: str,
        summary: str,
        risk_id: str,
        rule_id: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    occurred_at, actor, action, evidence_kind, summary, risk_id, rule_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, actor, action, evidence_kind, summary, risk_id, rule_id),
            )
            connection.commit()
