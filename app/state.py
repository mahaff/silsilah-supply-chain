"""UI state. This module loads data. It does not calculate metrics itself."""

from __future__ import annotations

import reflex as rx

from domain.evidence import evidence_label
from domain.metrics import build_metrics
from domain.models import status_label
from governance.status import build_governance_status
from llm.base import FactPacket
from llm.null_provider import get_provider
from persistence.connection import load_region_config
from persistence.repository import RegionRepository
from persistence.seed import seed_region


class WarRoomState(rx.State):
    """The selected region and the rows currently on screen."""

    region_code: str = "ksa"
    loading: bool = True
    error_message: str = ""

    region_display_name: str = ""
    organization_id: str = ""
    organization_name: str = ""
    supply_chain_id: str = ""
    supply_chain_name: str = ""
    currency: str = ""

    suppliers: list[dict[str, str]] = []
    products: list[dict[str, str]] = []
    inventory: list[dict[str, str]] = []
    orders: list[dict[str, str]] = []
    shipments: list[dict[str, str]] = []
    metrics: list[dict[str, str]] = []

    order_line_count: str = "0"
    governance_classification: str = "Synthetic"
    governance_references_loaded: str = "0"
    governance_disclaimer: str = ""
    governance_note: str = ""
    audit_summary: str = ""
    audit_at: str = ""
    reasoning_note: str = ""
    reasoning_provider: str = "null"

    def load_region(self):
        """Load whichever region is already selected. Used when the page opens."""
        yield from self._reload()

    def select_region(self, region_code: str):
        """Switch edition and load that database only."""
        self.region_code = region_code
        yield from self._reload()

    def _reload(self):
        # Yield once so the screen can show the loading line before SQLite work finishes.
        self.loading = True
        self.error_message = ""
        yield
        try:
            self._fill_from_database()
        except Exception as exc:
            self._clear_display()
            self.error_message = f"This region could not be loaded. {exc}"
        finally:
            self.loading = False

    def _fill_from_database(self) -> None:
        config = load_region_config(self.region_code)
        # Create the file only when it is missing. An existing file is left as it is.
        if not config.database_path.is_file():
            seed_region(self.region_code)

        repository = RegionRepository(self.region_code)
        scope = repository.load_scope()
        chain_id = scope.supply_chain.id
        suppliers = repository.list_suppliers(chain_id)
        products = repository.list_products(chain_id)
        orders = repository.list_purchase_orders(chain_id)
        order_rows = repository.list_purchase_order_rows(chain_id)
        lines = repository.list_purchase_order_lines(chain_id)
        shipments = repository.list_shipments(chain_id)
        inventory = repository.list_inventory(chain_id)
        metrics = build_metrics(suppliers, products, orders, shipments, inventory)
        governance = build_governance_status(
            scope.display_name,
            repository.governance_reference_count(),
            repository.latest_audit_event(),
        )
        note = get_provider().explain(
            FactPacket(
                region_code=scope.organization.region_code.value,
                supply_chain_id=chain_id,
                metrics=metrics,
            )
        )

        self.region_display_name = scope.display_name
        self.organization_id = scope.organization.id
        self.organization_name = scope.organization.name
        self.supply_chain_id = scope.supply_chain.id
        self.supply_chain_name = scope.supply_chain.name
        self.currency = scope.currency
        self.suppliers = [
            {
                "id": row.id,
                "name": row.name,
                "city": row.city,
                "status": status_label(row.status.value),
                "lead_time_days": str(row.lead_time_days),
            }
            for row in suppliers
        ]
        self.products = [
            {
                "sku": row.sku,
                "name": row.name,
                "category": row.category,
                "unit": row.unit,
            }
            for row in products
        ]
        self.inventory = [
            {
                "warehouse_name": row.warehouse_name,
                "sku": row.sku,
                "product_name": row.product_name,
                "on_hand": str(row.on_hand),
                "reorder_point": str(row.reorder_point),
                "below_reorder": "Yes" if row.below_reorder else "No",
            }
            for row in inventory
        ]
        self.orders = [
            {
                "id": row.id,
                "supplier_name": row.supplier_name,
                "warehouse_name": row.warehouse_name,
                "status": status_label(row.status.value),
                "ordered_on": row.ordered_on,
                "expected_on": row.expected_on,
            }
            for row in order_rows
        ]
        self.shipments = [
            {
                "id": row.id,
                "purchase_order_id": row.purchase_order_id,
                "origin": row.origin,
                "destination": row.destination,
                "status": status_label(row.status.value),
                "departed_on": row.departed_on or "Not recorded",
                "eta": row.eta,
                "arrived_on": row.arrived_on or "Not recorded",
            }
            for row in shipments
        ]
        self.metrics = [
            {
                "key": metric.key,
                "label": metric.label,
                "value": str(metric.value),
                "evidence_label": evidence_label(metric.evidence_kind),
                "explanation": metric.explanation,
            }
            for metric in metrics
        ]
        self.order_line_count = str(len(lines))
        self.governance_classification = governance.data_classification
        self.governance_references_loaded = str(governance.references_loaded)
        self.governance_disclaimer = governance.disclaimer
        self.governance_note = governance.references_note
        self.audit_summary = governance.latest_audit_summary
        self.audit_at = governance.latest_audit_at
        self.reasoning_note = note.text
        self.reasoning_provider = note.provider_name

    def _clear_display(self) -> None:
        self.region_display_name = ""
        self.organization_id = ""
        self.organization_name = ""
        self.supply_chain_id = ""
        self.supply_chain_name = ""
        self.currency = ""
        self.suppliers = []
        self.products = []
        self.inventory = []
        self.orders = []
        self.shipments = []
        self.metrics = []
        self.order_line_count = "0"
        self.governance_references_loaded = "0"
        self.governance_disclaimer = ""
        self.governance_note = ""
        self.audit_summary = ""
        self.audit_at = ""
        self.reasoning_note = ""
