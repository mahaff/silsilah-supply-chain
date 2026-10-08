"""UI state. This module loads data. It does not calculate metrics itself."""

from __future__ import annotations

import reflex as rx

from datetime import datetime, timezone

from domain.evidence import evidence_label
from domain.metrics import build_metrics
from domain.models import status_label
from domain.risks import Risk, count_open
from governance.status import build_governance_status
from llm.base import FactPacket
from llm.null_provider import get_provider
from persistence.connection import load_region_config
from persistence.repository import RegionRepository
from persistence.seed import seed_region
from prediction.model import PredictionSnapshot, build_prediction_snapshot


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

    dataset_as_of: str = ""
    open_risk_count: str = "0"
    inventory_risk_count: str = "0"
    shipment_risk_count: str = "0"
    supplier_risk_count: str = "0"
    attention_risk_count: str = "0"
    watch_risk_count: str = "0"
    risks: list[dict[str, str]] = []
    supplier_indicators: list[dict[str, str]] = []
    selected_risk_id: str = ""
    selected_title: str = ""
    selected_explanation: str = ""
    selected_rule_id: str = ""
    selected_severity_reason: str = ""
    selected_entities: str = ""
    selected_evidence: str = ""
    selected_status: str = ""
    selected_rereview: str = ""

    prediction_disclaimer: str = ""
    prediction_target: str = ""
    prediction_counts: str = ""
    prediction_chrono_text: str = ""
    prediction_random_text: str = ""
    prediction_operational_note: str = ""
    prediction_estimates: list[dict[str, str]] = []

    def load_region(self):
        """Load whichever region is already selected. Used when the page opens."""
        yield from self._reload()

    def select_region(self, region_code: str):
        """Switch edition and load that database only."""
        self.region_code = region_code
        self.selected_risk_id = ""
        yield from self._reload()

    def select_risk(self, risk_id: str):
        """Show the evidence for one risk from the register already on screen."""
        self.selected_risk_id = risk_id
        match = next((row for row in self.risks if row["id"] == risk_id), None)
        if match is None:
            self._clear_risk_detail()
            return
        self.selected_title = match["title"]
        self.selected_explanation = match["explanation"]
        self.selected_rule_id = match["rule_id"]
        self.selected_severity_reason = match["severity_reason"]
        self.selected_entities = match["entities"]
        self.selected_evidence = match["evidence"]
        self.selected_status = match["status_label"]
        self.selected_rereview = match["re_review_note"]

    def mark_reviewed(self):
        self._set_risk_status("reviewed")

    def mark_resolved(self):
        self._set_risk_status("resolved")

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
        risks, indicators = repository.load_risks(now=_utc_now())
        counts = count_open(risks)
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
        self.dataset_as_of = repository.dataset_as_of()
        self.open_risk_count = str(counts["open"])
        self.inventory_risk_count = str(counts["inventory"])
        self.shipment_risk_count = str(counts["shipment"])
        self.supplier_risk_count = str(counts["supplier"])
        self.attention_risk_count = str(counts["attention"])
        self.watch_risk_count = str(counts["watch"])
        self.risks = [_risk_row(risk) for risk in risks]
        self.supplier_indicators = [
            {
                "supplier_name": indicator.supplier_name,
                "delayed_shipment_count": str(indicator.delayed_shipment_count),
                "linked_shipment_count": str(indicator.linked_shipment_count),
                "delay_proportion_text": indicator.delay_proportion_text,
                "order_share_text": indicator.order_share_text,
                "note": indicator.note,
            }
            for indicator in indicators
        ]
        self._remember_risk_detail(risks)
        self._fill_prediction(
            build_prediction_snapshot(
                history=repository.list_shipment_history(chain_id),
                suppliers=suppliers,
                shipments=shipments,
                orders=orders,
                dataset_as_of=self.dataset_as_of,
            )
        )

    def _set_risk_status(self, status: str):
        if not self.selected_risk_id:
            self.error_message = "Select a risk in the register before updating its status."
            return
        try:
            repository = RegionRepository(self.region_code)
            repository.set_risk_status(self.selected_risk_id, status, now=_utc_now())
            self.error_message = ""
        except Exception as exc:
            self.error_message = f"The status was not changed. {exc}"
            return
        self._fill_from_database()

    def _remember_risk_detail(self, risks: list[Risk]) -> None:
        if not self.selected_risk_id:
            self._clear_risk_detail()
            return
        match = next((risk for risk in risks if risk.id == self.selected_risk_id), None)
        if match is None:
            self.selected_risk_id = ""
            self._clear_risk_detail()
            return
        self.selected_title = match.title
        self.selected_explanation = match.explanation
        self.selected_rule_id = match.rule_id
        self.selected_severity_reason = match.severity_reason
        self.selected_entities = ", ".join(match.entity_ids)
        self.selected_evidence = "\n".join(match.evidence_lines)
        self.selected_status = {"open": "Open", "reviewed": "Reviewed", "resolved": "Resolved"}.get(
            match.status, match.status
        )
        self.selected_rereview = match.re_review_note

    def _fill_prediction(self, snapshot: PredictionSnapshot) -> None:
        self.prediction_disclaimer = snapshot.disclaimer
        self.prediction_target = snapshot.target
        self.prediction_counts = snapshot.counts_summary()
        self.prediction_chrono_text = snapshot.chronological.summary()
        self.prediction_random_text = snapshot.random_split.summary()
        self.prediction_operational_note = snapshot.operational_note
        self.prediction_estimates = [_estimate_row(estimate) for estimate in snapshot.estimates]

    def _clear_prediction(self) -> None:
        self.prediction_disclaimer = ""
        self.prediction_target = ""
        self.prediction_counts = ""
        self.prediction_chrono_text = ""
        self.prediction_random_text = ""
        self.prediction_operational_note = ""
        self.prediction_estimates = []

    def _clear_risk_detail(self) -> None:
        self.selected_title = ""
        self.selected_explanation = ""
        self.selected_rule_id = ""
        self.selected_severity_reason = ""
        self.selected_entities = ""
        self.selected_evidence = ""
        self.selected_status = ""
        self.selected_rereview = ""

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
        self.dataset_as_of = ""
        self.open_risk_count = "0"
        self.inventory_risk_count = "0"
        self.shipment_risk_count = "0"
        self.supplier_risk_count = "0"
        self.attention_risk_count = "0"
        self.watch_risk_count = "0"
        self.risks = []
        self.supplier_indicators = []
        self.selected_risk_id = ""
        self._clear_risk_detail()
        self._clear_prediction()


def _estimate_row(estimate) -> dict[str, str]:
    return {
        "shipment_id": estimate.shipment_id,
        "outcome": "Estimate" if estimate.scored else "Not scored",
        "probability": "" if estimate.probability is None else f"{estimate.probability:.2f}",
        "sentence": estimate.sentence,
        "reason": estimate.reason,
        "factors": "\n".join(item.sentence for item in estimate.contributions),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _risk_row(risk: Risk) -> dict[str, str]:
    category_labels = {
        "inventory": "Inventory",
        "shipment": "Shipment",
        "supplier": "Supplier",
    }
    severity_labels = {"attention": "Attention", "watch": "Watch"}
    status_labels = {"open": "Open", "reviewed": "Reviewed", "resolved": "Resolved"}
    return {
        "id": risk.id,
        "category_label": category_labels.get(risk.category, risk.category),
        "severity_label": severity_labels.get(risk.severity, risk.severity),
        "status_label": status_labels.get(risk.status, risk.status),
        "title": risk.title,
        "re_review": "Yes" if risk.re_review_note else "No",
        "explanation": risk.explanation,
        "rule_id": risk.rule_id,
        "severity_reason": risk.severity_reason,
        "entities": ", ".join(risk.entity_ids),
        "evidence": "\n".join(risk.evidence_lines),
        "re_review_note": risk.re_review_note,
    }
