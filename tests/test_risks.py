"""Deterministic risk rules, review persistence, and regional isolation."""

from datetime import date

import pytest

from domain.models import (
    DemandPeriod,
    InventoryRow,
    OrderStatus,
    PurchaseOrder,
    Shipment,
    ShipmentStatus,
    Supplier,
    SupplierStatus,
)
from domain.risks import (
    DATASET_AS_OF_DATE,
    DATASET_AS_OF_TEXT,
    MIN_SHIPMENTS_FOR_PROPORTION,
    RiskStatus,
    SEVERITY_REASONS,
    estimate_coverage,
    evidence_fingerprint,
    inventory_risks,
    reconcile_reviews,
    shipment_risks,
    supplier_indicators,
    supplier_risks,
)
from domain.risks import StoredReview
from persistence.repository import RegionRepository

FIXED_NOW = "2026-10-02T12:00:00+00:00"
LATER = "2026-10-02T13:00:00+00:00"


def test_reorder_rule_ignores_equal_quantities_and_states_coverage_limits():
    low = _inventory("INV-LOW", on_hand=4, reorder_point=5)
    equal = _inventory("INV-EQ", on_hand=5, reorder_point=5)
    periods = [
        _period("D1", "WH", "PRD", "2026-08-01", "2026-08-14", 14),
        _period("D2", "WH", "PRD", "2026-08-15", "2026-08-28", 14),
    ]
    risks = inventory_risks("ksa", [low, equal], periods, DATASET_AS_OF_DATE)
    assert [risk.id for risk in risks] == ["ksa:inventory.below_reorder:INV-LOW"]
    assert risks[0].severity == "attention"
    assert "Estimated days of coverage: 4" in risks[0].explanation
    assert "not a predicted stockout date" in risks[0].explanation
    assert "probability" not in risks[0].severity_reason

    thin = inventory_risks("ksa", [low], periods[:1], DATASET_AS_OF_DATE)
    assert "Insufficient demand history" in thin[0].explanation
    assert "No stockout date is estimated" in thin[0].explanation
    assert thin[0].evidence_fingerprint != risks[0].evidence_fingerprint


def test_coverage_needs_two_periods_and_does_not_invent_a_date():
    missing = estimate_coverage(10, "WH", "PRD", [])
    assert missing.available is False
    assert missing.days is None
    one = estimate_coverage(
        10,
        "WH",
        "PRD",
        [_period("D1", "WH", "PRD", "2026-08-01", "2026-08-10", 10)],
    )
    assert one.available is False
    two = estimate_coverage(
        15,
        "WH",
        "PRD",
        [
            _period("D1", "WH", "PRD", "2026-08-01", "2026-08-14", 14),
            _period("D2", "WH", "PRD", "2026-08-15", "2026-08-28", 14),
        ],
    )
    assert two.available is True
    assert two.days == 15


def test_overdue_uses_the_dataset_date_not_a_clock():
    shipment = _shipment("SHP", "PO", ShipmentStatus.IN_TRANSIT, "2026-09-30")
    order = _order("PO", "SUP")
    supplier = _supplier("SUP")
    early = shipment_risks("ksa", [shipment], [order], [supplier], date(2026, 9, 30))
    assert early == []
    late = shipment_risks("ksa", [shipment], [order], [supplier], DATASET_AS_OF_DATE)
    assert [risk.rule_id for risk in late] == ["shipment.eta_passed_not_delivered"]
    assert DATASET_AS_OF_TEXT in late[0].explanation
    delivered = _shipment("SHP2", "PO", ShipmentStatus.DELIVERED, "2026-09-01")
    assert shipment_risks("ksa", [delivered], [order], [supplier], DATASET_AS_OF_DATE) == []


def test_delayed_status_is_separate_from_overdue():
    shipment = _shipment("SHP", "PO", ShipmentStatus.DELAYED, "2026-09-22")
    risks = shipment_risks(
        "ksa",
        [shipment],
        [_order("PO", "SUP")],
        [_supplier("SUP")],
        DATASET_AS_OF_DATE,
    )
    assert {risk.rule_id for risk in risks} == {
        "shipment.delayed_status",
        "shipment.eta_passed_not_delivered",
    }
    delayed = next(risk for risk in risks if risk.rule_id == "shipment.delayed_status")
    assert "not a forecast" in delayed.explanation
    assert "SUP" in delayed.entity_ids


def test_delay_proportion_is_withheld_until_three_shipments():
    supplier = _supplier("SUP")
    orders = [_order(f"PO-{index}", "SUP") for index in range(2)]
    shipments = [
        _shipment("SHP-1", "PO-0", ShipmentStatus.DELAYED, "2026-09-01"),
        _shipment("SHP-2", "PO-1", ShipmentStatus.DELIVERED, "2026-08-01"),
    ]
    indicator = supplier_indicators([supplier], shipments, orders)[0]
    assert indicator.delayed_shipment_count == 1
    assert indicator.linked_shipment_count == 2
    assert "Insufficient evidence" in indicator.delay_proportion_text
    assert str(MIN_SHIPMENTS_FOR_PROPORTION) in indicator.delay_proportion_text
    assert "not a validated supplier reliability prediction" in indicator.note.lower()

    orders.append(_order("PO-2", "SUP"))
    shipments.append(_shipment("SHP-3", "PO-2", ShipmentStatus.PLANNED, "2026-10-06"))
    enough = supplier_indicators([supplier], shipments, orders)[0]
    assert enough.delay_proportion_text == "1 of 3 linked shipments are delayed."


def test_concentration_alert_needs_three_orders_and_half_the_chain():
    suppliers = [_supplier("A", "Alpha"), _supplier("B", "Beta")]
    orders = [
        _order("PO-1", "A"),
        _order("PO-2", "A"),
        _order("PO-3", "A"),
        _order("PO-4", "B"),
    ]
    risks = supplier_risks("ksa", suppliers, [], orders, DATASET_AS_OF_DATE)
    assert [risk.rule_id for risk in risks] == ["supplier.order_share"]
    assert risks[0].severity == "watch"
    assert "probability" not in risks[0].explanation
    thin = supplier_risks(
        "ksa",
        suppliers,
        [],
        [_order("PO-1", "A"), _order("PO-2", "A")],
        DATASET_AS_OF_DATE,
    )
    assert thin == []


def test_severity_mapping_is_documented_for_every_rule():
    for rule_id, reason in SEVERITY_REASONS.items():
        assert reason
        lowered = reason.lower()
        assert "probability" not in lowered
        assert "confidence" not in lowered


def test_resolved_status_survives_recalculation_when_evidence_matches(regional_databases):
    repository = RegionRepository("ksa", database_path=regional_databases["ksa"])
    risk_id = "ksa:inventory.below_reorder:KSA-INV-002"
    repository.set_risk_status(risk_id, RiskStatus.RESOLVED, now=FIXED_NOW)
    risks, _indicators = repository.load_risks(now=LATER)
    risk = _find(risks, risk_id)
    assert risk.status == RiskStatus.RESOLVED
    assert risk.re_review_note == ""
    audits = [
        event
        for event in repository.list_audit_events()
        if event.action == "risk_status_changed"
    ]
    assert len(audits) == 1
    assert audits[0].actor == "local_user"
    assert audits[0].risk_id == risk_id
    assert audits[0].rule_id == "inventory.below_reorder"
    assert audits[0].evidence_kind == "human_decision"
    assert "15" in risk.explanation


def test_changed_evidence_reopens_a_resolved_risk(regional_databases):
    repository = RegionRepository("ksa", database_path=regional_databases["ksa"])
    risk_id = "ksa:inventory.below_reorder:KSA-INV-002"
    repository.set_risk_status(risk_id, RiskStatus.RESOLVED, now=FIXED_NOW)
    with repository._session() as connection:
        connection.execute(
            "UPDATE inventory SET on_hand = 14 WHERE id = 'KSA-INV-002'"
        )
        connection.commit()
    risks, _indicators = repository.load_risks(now=LATER)
    risk = _find(risks, risk_id)
    assert risk.status == RiskStatus.OPEN
    assert risk.status != RiskStatus.RESOLVED
    assert "needs re-review" in risk.re_review_note
    assert "14" in " ".join(risk.evidence_lines)
    reopened = [
        event
        for event in repository.list_audit_events()
        if event.action == "risk_reopened_for_rereview"
    ]
    assert len(reopened) == 1
    assert reopened[0].actor == "system"
    assert reopened[0].risk_id == risk_id
    again, _indicators = repository.load_risks(now="2026-10-02T14:00:00+00:00")
    assert _find(again, risk_id).status == RiskStatus.OPEN
    assert len(
        [
            event
            for event in repository.list_audit_events()
            if event.action == "risk_reopened_for_rereview"
        ]
    ) == 1


def test_review_status_does_not_cross_regions(regional_databases):
    ksa = RegionRepository("ksa", database_path=regional_databases["ksa"])
    pakistan = RegionRepository("pakistan", database_path=regional_databases["pakistan"])
    ksa.set_risk_status(
        "ksa:shipment.delayed_status:KSA-SHP-003",
        RiskStatus.REVIEWED,
        now=FIXED_NOW,
    )
    assert pakistan.list_reviews() == {}
    ksa_risks, _indicators = ksa.load_risks(now=LATER)
    pakistan_risks, _indicators = pakistan.load_risks(now=LATER)
    ksa_ids = {risk.id for risk in ksa_risks}
    pakistan_ids = {risk.id for risk in pakistan_risks}
    assert ksa_ids.isdisjoint(pakistan_ids)
    assert all(risk_id.startswith("ksa:") for risk_id in ksa_ids)
    assert all(risk_id.startswith("pakistan:") for risk_id in pakistan_ids)
    assert _find(ksa_risks, "ksa:shipment.delayed_status:KSA-SHP-003").status == "reviewed"


def test_seeded_regions_match_the_published_rules(regional_databases):
    ksa = RegionRepository("ksa", database_path=regional_databases["ksa"])
    pakistan = RegionRepository("pakistan", database_path=regional_databases["pakistan"])
    assert ksa.dataset_as_of() == DATASET_AS_OF_TEXT
    assert pakistan.dataset_as_of() == DATASET_AS_OF_TEXT
    ksa_risks, ksa_indicators = ksa.load_risks(now=FIXED_NOW)
    pakistan_risks, pakistan_indicators = pakistan.load_risks(now=FIXED_NOW)
    assert {risk.id for risk in ksa_risks} == {
        "ksa:inventory.below_reorder:KSA-INV-002",
        "ksa:inventory.below_reorder:KSA-INV-004",
        "ksa:shipment.delayed_status:KSA-SHP-003",
        "ksa:shipment.eta_passed_not_delivered:KSA-SHP-002",
        "ksa:shipment.eta_passed_not_delivered:KSA-SHP-003",
        "ksa:supplier.delayed_shipment_present:KSA-SUP-002",
    }
    rice = _find(ksa_risks, "ksa:inventory.below_reorder:KSA-INV-002")
    cartons = _find(ksa_risks, "ksa:inventory.below_reorder:KSA-INV-004")
    assert "Estimated days of coverage: 15" in rice.explanation
    assert "Insufficient demand history" in cartons.explanation
    assert {risk.id for risk in pakistan_risks} == {
        "pakistan:inventory.below_reorder:PAK-INV-001",
        "pakistan:inventory.below_reorder:PAK-INV-004",
        "pakistan:inventory.below_reorder:PAK-INV-007",
        "pakistan:shipment.delayed_status:PAK-SHP-002",
        "pakistan:shipment.delayed_status:PAK-SHP-003",
        "pakistan:shipment.eta_passed_not_delivered:PAK-SHP-002",
        "pakistan:shipment.eta_passed_not_delivered:PAK-SHP-003",
        "pakistan:supplier.delayed_shipment_present:PAK-SUP-001",
        "pakistan:supplier.delayed_shipment_present:PAK-SUP-004",
    }
    water = _find(pakistan_risks, "pakistan:inventory.below_reorder:PAK-INV-001")
    assert "Estimated days of coverage: 20" in water.explanation
    assert all("Insufficient evidence" in item.delay_proportion_text for item in ksa_indicators)
    assert all(
        "Insufficient evidence" in item.delay_proportion_text for item in pakistan_indicators
    )
    oasis = next(item for item in ksa_indicators if item.supplier_id == "KSA-SUP-001")
    assert oasis.order_share_text == "2 of 7 purchase orders in this supply chain."
    assert all(risk.rule_id != "supplier.order_share" for risk in ksa_risks + pakistan_risks)
    assert ksa.governance_reference_count() == 0


def test_reconcile_does_not_keep_resolved_when_fingerprint_changes():
    original = evidence_fingerprint({"on_hand": "15", "reorder_point": "30"})
    changed = evidence_fingerprint({"on_hand": "14", "reorder_point": "30"})
    risk = inventory_risks(
        "ksa",
        [_inventory("INV", on_hand=14, reorder_point=30)],
        [],
        DATASET_AS_OF_DATE,
    )[0]
    risk.evidence_fingerprint = changed
    stored = StoredReview(
        risk_id=risk.id,
        status=RiskStatus.RESOLVED,
        evidence_fingerprint=original,
        actor="local_user",
        updated_at=FIXED_NOW,
        re_review_required=False,
        re_review_note="",
    )
    reconciled, updates = reconcile_reviews([risk], {risk.id: stored})
    assert reconciled[0].status == RiskStatus.OPEN
    assert "not kept" in reconciled[0].re_review_note
    assert updates[0].write_audit is True


def test_unknown_status_is_rejected(regional_databases):
    repository = RegionRepository("ksa", database_path=regional_databases["ksa"])
    with pytest.raises(ValueError, match="open, reviewed, or resolved"):
        repository.set_risk_status(
            "ksa:inventory.below_reorder:KSA-INV-002",
            "approved",
            now=FIXED_NOW,
        )


def _find(risks, risk_id):
    return next(risk for risk in risks if risk.id == risk_id)


def _inventory(row_id: str, on_hand: int, reorder_point: int) -> InventoryRow:
    return InventoryRow(
        id=row_id,
        supply_chain_id="SC",
        warehouse_id="WH",
        product_id="PRD",
        warehouse_name="Riyadh DC",
        sku="SKU",
        product_name="Rice 5kg",
        on_hand=on_hand,
        reorder_point=reorder_point,
    )


def _period(
    row_id: str,
    warehouse_id: str,
    product_id: str,
    start: str,
    end: str,
    quantity: int,
) -> DemandPeriod:
    return DemandPeriod(
        id=row_id,
        supply_chain_id="SC",
        warehouse_id=warehouse_id,
        product_id=product_id,
        period_start=start,
        period_end=end,
        quantity_issued=quantity,
    )


def _shipment(row_id: str, order_id: str, status: ShipmentStatus, eta: str) -> Shipment:
    return Shipment(
        id=row_id,
        purchase_order_id=order_id,
        origin="Dammam",
        destination="Riyadh",
        status=status,
        departed_on="2026-09-16" if status != ShipmentStatus.PLANNED else None,
        eta=eta,
        arrived_on="2026-09-18" if status == ShipmentStatus.DELIVERED else None,
    )


def _order(order_id: str, supplier_id: str) -> PurchaseOrder:
    return PurchaseOrder(
        id=order_id,
        supply_chain_id="SC",
        supplier_id=supplier_id,
        warehouse_id="WH",
        status=OrderStatus.OPEN,
        ordered_on="2026-09-01",
        expected_on="2026-09-20",
    )


def _supplier(supplier_id: str, name: str = "Demo Supplier") -> Supplier:
    return Supplier(
        id=supplier_id,
        supply_chain_id="SC",
        name=name,
        city="Riyadh",
        status=SupplierStatus.ACTIVE,
        lead_time_days=5,
    )
