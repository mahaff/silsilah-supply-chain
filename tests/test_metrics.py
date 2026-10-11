"""Metric rules, plus the counts produced by the synthetic datasets."""

from domain.evidence import EvidenceKind
from domain.metrics import Metric, build_metrics, low_stock_lines, open_purchase_orders
from domain.models import (
    InventoryRow,
    OrderStatus,
    PurchaseOrder,
    Shipment,
    ShipmentStatus,
    Supplier,
    SupplierStatus,
)
from llm.base import FactPacket
from llm.null_provider import get_provider
from persistence.repository import RegionRepository

KSA_EXPECTED = {
    "suppliers": 6,
    "products": 10,
    "open_purchase_orders": 3,
    "shipments_in_transit": 1,
    "delayed_shipments": 1,
    "low_stock_lines": 2,
}

PAKISTAN_EXPECTED = {
    "suppliers": 6,
    "products": 10,
    "open_purchase_orders": 2,
    "shipments_in_transit": 0,
    "delayed_shipments": 2,
    "low_stock_lines": 3,
}


def _inventory(on_hand: int, reorder_point: int) -> InventoryRow:
    return InventoryRow(
        id="INV",
        supply_chain_id="SC",
        warehouse_id="WH",
        product_id="PRD",
        warehouse_name="DC",
        sku="SKU",
        product_name="Item",
        on_hand=on_hand,
        reorder_point=reorder_point,
    )


def _order(status: OrderStatus) -> PurchaseOrder:
    return PurchaseOrder(
        id="PO",
        supply_chain_id="SC",
        supplier_id="SUP",
        warehouse_id="WH",
        status=status,
        ordered_on="2026-09-01",
        expected_on="2026-09-20",
    )


def test_low_stock_rule_is_strictly_below_reorder_point():
    metric = low_stock_lines(
        [
            _inventory(5, 5),
            _inventory(4, 5),
            _inventory(6, 5),
        ]
    )
    assert metric.value == 1
    assert metric.evidence_kind == EvidenceKind.DETERMINISTIC_RULE


def test_open_purchase_orders_ignore_partial_and_closed():
    metric = open_purchase_orders(
        [
            _order(OrderStatus.OPEN),
            _order(OrderStatus.PARTIAL),
            _order(OrderStatus.CLOSED),
        ]
    )
    assert metric.value == 1
    assert metric.evidence_kind == EvidenceKind.DETERMINISTIC_RULE


def test_supplier_count_is_a_database_fact():
    suppliers = [
        Supplier(
            id="SUP-1",
            supply_chain_id="SC",
            name="Demo",
            city="Riyadh",
            status=SupplierStatus.ACTIVE,
            lead_time_days=4,
        )
    ]
    metrics = build_metrics(
        suppliers,
        [],
        [],
        [
            Shipment(
                id="SHP",
                purchase_order_id="PO",
                origin="A",
                destination="B",
                status=ShipmentStatus.DELAYED,
                departed_on="2026-09-01",
                eta="2026-09-02",
                arrived_on=None,
            )
        ],
        [],
    )
    by_key = {metric.key: metric for metric in metrics}
    assert by_key["suppliers"].value == 1
    assert by_key["suppliers"].evidence_kind == EvidenceKind.DATABASE_FACT
    assert by_key["delayed_shipments"].value == 1
    assert by_key["shipments_in_transit"].value == 0


def test_seeded_regions_have_different_metric_profiles(regional_databases):
    assert _metric_map("ksa", regional_databases["ksa"]) == KSA_EXPECTED
    assert _metric_map("pakistan", regional_databases["pakistan"]) == PAKISTAN_EXPECTED


def test_null_provider_does_not_echo_calculated_values():
    packet = FactPacket(
        region_code="ksa",
        supply_chain_id="KSA-SC-001",
        metrics=[
            Metric(
                key="low_stock_lines",
                label="Stock lines below reorder point",
                value=424242,
                evidence_kind=EvidenceKind.DETERMINISTIC_RULE,
                explanation="Test packet.",
            )
        ],
    )
    note = get_provider().explain(packet)
    assert note.available is False
    assert note.provider_name == "null"
    assert note.evidence_kind == EvidenceKind.LLM_REASONING
    assert "424242" not in note.text
    assert packet.metrics[0].value == 424242


def _metric_map(region_code: str, database_path) -> dict[str, int]:
    repository = RegionRepository(region_code, database_path=database_path)
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    metrics = build_metrics(
        repository.list_suppliers(chain_id),
        repository.list_products(chain_id),
        repository.list_purchase_orders(chain_id),
        repository.list_shipments(chain_id),
        repository.list_inventory(chain_id),
    )
    return {metric.key: metric.value for metric in metrics}
