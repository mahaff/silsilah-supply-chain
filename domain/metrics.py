"""MVP metrics.

A straight count of stored rows is a database fact.
A count that keeps only rows matching a condition is a deterministic rule.
Both are plain Python. No model and no language model is involved.
"""

from pydantic import BaseModel, ConfigDict

from domain.evidence import EvidenceKind
from domain.models import (
    InventoryRow,
    OrderStatus,
    Product,
    PurchaseOrder,
    Shipment,
    ShipmentStatus,
    Supplier,
)


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: int
    evidence_kind: EvidenceKind
    explanation: str


def supplier_count(suppliers: list[Supplier]) -> Metric:
    return Metric(
        key="suppliers",
        label="Suppliers",
        value=len(suppliers),
        evidence_kind=EvidenceKind.DATABASE_FACT,
        explanation="Every supplier row stored for this supply chain. No filter is applied.",
    )


def product_count(products: list[Product]) -> Metric:
    return Metric(
        key="products",
        label="Products",
        value=len(products),
        evidence_kind=EvidenceKind.DATABASE_FACT,
        explanation="Every product row stored for this supply chain. No filter is applied.",
    )


def open_purchase_orders(orders: list[PurchaseOrder]) -> Metric:
    value = sum(1 for order in orders if order.status == OrderStatus.OPEN)
    return Metric(
        key="open_purchase_orders",
        label="Open purchase orders",
        value=value,
        evidence_kind=EvidenceKind.DETERMINISTIC_RULE,
        explanation="Purchase orders whose stored status is open. Partial and closed orders are left out.",
    )


def shipments_in_transit(shipments: list[Shipment]) -> Metric:
    value = sum(1 for shipment in shipments if shipment.status == ShipmentStatus.IN_TRANSIT)
    return Metric(
        key="shipments_in_transit",
        label="Shipments in transit",
        value=value,
        evidence_kind=EvidenceKind.DETERMINISTIC_RULE,
        explanation="Shipments whose stored status is in transit.",
    )


def delayed_shipments(shipments: list[Shipment]) -> Metric:
    value = sum(1 for shipment in shipments if shipment.status == ShipmentStatus.DELAYED)
    return Metric(
        key="delayed_shipments",
        label="Delayed shipments",
        value=value,
        evidence_kind=EvidenceKind.DETERMINISTIC_RULE,
        explanation="Shipments whose stored status is delayed.",
    )


def low_stock_lines(inventory: list[InventoryRow]) -> Metric:
    # Equal quantities are not low. Only a smaller on-hand value matches.
    value = sum(1 for row in inventory if row.on_hand < row.reorder_point)
    return Metric(
        key="low_stock_lines",
        label="Stock lines below reorder point",
        value=value,
        evidence_kind=EvidenceKind.DETERMINISTIC_RULE,
        explanation="Inventory rows where on-hand quantity is lower than the reorder point.",
    )


def build_metrics(
    suppliers: list[Supplier],
    products: list[Product],
    orders: list[PurchaseOrder],
    shipments: list[Shipment],
    inventory: list[InventoryRow],
) -> list[Metric]:
    """Return the six MVP metrics in screen order."""
    return [
        supplier_count(suppliers),
        product_count(products),
        open_purchase_orders(orders),
        shipments_in_transit(shipments),
        delayed_shipments(shipments),
        low_stock_lines(inventory),
    ]
