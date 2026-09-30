"""Deterministic risk rules for one regional supply chain.

These rules read stored rows and compare them. They do not predict a delay,
a stockout date, or a supplier reliability score. Severity is a plain label
for how direct the recorded condition is, not a probability.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from domain.evidence import EvidenceKind
from domain.models import (
    DemandPeriod,
    InventoryRow,
    PurchaseOrder,
    Shipment,
    ShipmentStatus,
    Supplier,
)

# Both regions use this date for overdue checks. It is part of the synthetic
# dataset. It is not the clock on the computer running Silsilah.
DATASET_AS_OF_DATE = date(2026, 10, 1)
DATASET_AS_OF_TEXT = "2026-10-01"
DATASET_AS_OF_LABEL = "Synthetic dataset as-of date"

# A delay proportion needs at least this many linked shipments. Fewer than
# that is reported as insufficient evidence.
MIN_SHIPMENTS_FOR_PROPORTION = 3

# A concentration alert needs both a large enough share and several orders.
# Two orders out of four is half, but two orders is too thin to alert on.
MIN_ORDERS_FOR_CONCENTRATION = 3


class RiskCategory(str):
    INVENTORY = "inventory"
    SHIPMENT = "shipment"
    SUPPLIER = "supplier"


class RiskSeverity(str):
    WATCH = "watch"
    ATTENTION = "attention"


class RiskStatus(str):
    OPEN = "open"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


# Why each rule uses its severity. Kept next to the rules so the mapping
# cannot drift from the code that applies it.
SEVERITY_REASONS: dict[str, str] = {
    "inventory.below_reorder": (
        "Attention, because on-hand quantity is already under the reorder point "
        "stored on that inventory row. This is a warning, not a stockout date."
    ),
    "shipment.delayed_status": (
        "Attention, because the shipment row already says delayed. "
        "The rule does not forecast a future delay."
    ),
    "shipment.eta_passed_not_delivered": (
        "Attention, because the stored expected arrival date is before the "
        "synthetic dataset as-of date and the shipment is not delivered."
    ),
    "supplier.delayed_shipment_present": (
        "Watch, because at least one linked shipment is delayed. "
        "One recorded delay in this sample is not a reliability rating."
    ),
    "supplier.order_share": (
        "Watch, because one supplier holds at least half of this chain's "
        "purchase orders and at least three of them. This is a count of rows "
        "in the synthetic file, not a market-concentration score."
    ),
}

RULE_SEVERITY: dict[str, str] = {
    "inventory.below_reorder": RiskSeverity.ATTENTION,
    "shipment.delayed_status": RiskSeverity.ATTENTION,
    "shipment.eta_passed_not_delivered": RiskSeverity.ATTENTION,
    "supplier.delayed_shipment_present": RiskSeverity.WATCH,
    "supplier.order_share": RiskSeverity.WATCH,
}

RULE_CATEGORY: dict[str, str] = {
    "inventory.below_reorder": RiskCategory.INVENTORY,
    "shipment.delayed_status": RiskCategory.SHIPMENT,
    "shipment.eta_passed_not_delivered": RiskCategory.SHIPMENT,
    "supplier.delayed_shipment_present": RiskCategory.SUPPLIER,
    "supplier.order_share": RiskCategory.SUPPLIER,
}


class CoverageEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    days: int | None = None
    text: str


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    region_code: str
    category: str
    severity: str
    status: str = RiskStatus.OPEN
    title: str
    explanation: str
    severity_reason: str
    entity_ids: list[str]
    evidence_lines: list[str]
    evidence_fingerprint: str
    rule_id: str
    dataset_as_of: str
    evidence_kind: EvidenceKind = EvidenceKind.DETERMINISTIC_RULE
    re_review_note: str = ""


class SupplierIndicator(BaseModel):
    """Counts from this synthetic file. Not a reliability prediction."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    supplier_name: str
    delayed_shipment_count: int = Field(ge=0)
    linked_shipment_count: int = Field(ge=0)
    delay_proportion_text: str
    purchase_order_count: int = Field(ge=0)
    order_share_text: str
    note: str


class StoredReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    status: str
    evidence_fingerprint: str
    actor: str
    updated_at: str
    re_review_required: bool
    re_review_note: str


class ReviewUpdate(BaseModel):
    """A review-row change caused by recalculation, before any new click."""

    model_config = ConfigDict(extra="forbid")

    risk_id: str
    rule_id: str
    status: str
    evidence_fingerprint: str
    re_review_required: bool
    re_review_note: str
    write_audit: bool
    previous_status: str


INDICATOR_NOTE = (
    "Indicator from this synthetic dataset. Not a validated supplier reliability prediction."
)

INSUFFICIENT_COVERAGE = (
    "Insufficient demand history. No stockout date is estimated."
)


def evidence_fingerprint(parts: dict[str, str]) -> str:
    """Stable text for the fields that justify a rule.

    A reviewed status is kept only when this text still matches.
    """
    return "|".join(f"{key}={parts[key]}" for key in sorted(parts))


def _risk_id(region_code: str, rule_id: str, entity_id: str) -> str:
    return f"{region_code}:{rule_id}:{entity_id}"


def _inclusive_days(period: DemandPeriod) -> int:
    start = date.fromisoformat(period.period_start)
    end = date.fromisoformat(period.period_end)
    return (end - start).days + 1


def estimate_coverage(
    on_hand: int,
    warehouse_id: str,
    product_id: str,
    periods: list[DemandPeriod],
) -> CoverageEstimate:
    """Days of coverage from stored issue periods, or an insufficient-data note.

    At least two periods are required. The result is whole days, rounded down.
    It is not a calendar date on which stock runs out.
    """
    matched = [
        period
        for period in periods
        if period.warehouse_id == warehouse_id and period.product_id == product_id
    ]
    if len(matched) < 2:
        return CoverageEstimate(available=False, text=INSUFFICIENT_COVERAGE)
    total_quantity = sum(period.quantity_issued for period in matched)
    total_days = sum(_inclusive_days(period) for period in matched)
    if total_quantity <= 0 or total_days <= 0:
        return CoverageEstimate(available=False, text=INSUFFICIENT_COVERAGE)
    days = (on_hand * total_days) // total_quantity
    return CoverageEstimate(
        available=True,
        days=days,
        text=(
            f"Estimated days of coverage: {days}. "
            "Calculated from synthetic issue history. This is not a predicted stockout date."
        ),
    )


def inventory_risks(
    region_code: str,
    inventory: list[InventoryRow],
    periods: list[DemandPeriod],
    as_of: date,
) -> list[Risk]:
    risks: list[Risk] = []
    rule_id = "inventory.below_reorder"
    for row in inventory:
        if row.on_hand >= row.reorder_point:
            continue
        coverage = estimate_coverage(row.on_hand, row.warehouse_id, row.product_id, periods)
        coverage_token = str(coverage.days) if coverage.available else "insufficient"
        risks.append(
            Risk(
                id=_risk_id(region_code, rule_id, row.id),
                region_code=region_code,
                category=RULE_CATEGORY[rule_id],
                severity=RULE_SEVERITY[rule_id],
                title=f"{row.product_name} at {row.warehouse_name} is below its reorder point",
                explanation=(
                    f"On hand is {row.on_hand} and the reorder point is {row.reorder_point}. "
                    "This warning compares those two stored numbers. "
                    + coverage.text
                ),
                severity_reason=SEVERITY_REASONS[rule_id],
                entity_ids=[row.id, row.product_id, row.warehouse_id],
                evidence_lines=[
                    f"Inventory row {row.id}",
                    f"Product {row.product_name} ({row.sku})",
                    f"Warehouse {row.warehouse_name}",
                    f"On hand {row.on_hand}",
                    f"Reorder point {row.reorder_point}",
                    coverage.text,
                ],
                evidence_fingerprint=evidence_fingerprint(
                    {
                        "on_hand": str(row.on_hand),
                        "reorder_point": str(row.reorder_point),
                        "product_id": row.product_id,
                        "warehouse_id": row.warehouse_id,
                        "coverage_days": coverage_token,
                    }
                ),
                rule_id=rule_id,
                dataset_as_of=as_of.isoformat(),
            )
        )
    return risks


def shipment_risks(
    region_code: str,
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
    suppliers: list[Supplier],
    as_of: date,
) -> list[Risk]:
    orders_by_id = {order.id: order for order in orders}
    suppliers_by_id = {supplier.id: supplier for supplier in suppliers}
    risks: list[Risk] = []
    for shipment in shipments:
        order = orders_by_id.get(shipment.purchase_order_id)
        if order is None:
            continue
        supplier = suppliers_by_id.get(order.supplier_id)
        supplier_name = supplier.name if supplier is not None else order.supplier_id
        supplier_id = order.supplier_id
        if shipment.status == ShipmentStatus.DELAYED:
            risks.append(
                _shipment_risk(
                    region_code=region_code,
                    rule_id="shipment.delayed_status",
                    shipment=shipment,
                    supplier_id=supplier_id,
                    supplier_name=supplier_name,
                    as_of=as_of,
                    title=f"Shipment {shipment.id} is marked delayed",
                    explanation=(
                        f"Shipment {shipment.id} on purchase order {shipment.purchase_order_id} "
                        f"from {supplier_name} has stored status delayed. "
                        f"Its expected arrival date is {shipment.eta}. "
                        f"The {DATASET_AS_OF_LABEL.lower()} is {as_of.isoformat()}, "
                        "which is not today's date. This is the stored status, not a forecast."
                    ),
                    fingerprint_parts={
                        "purchase_order_id": shipment.purchase_order_id,
                        "status": shipment.status.value,
                        "supplier_id": supplier_id,
                    },
                )
            )
        eta = date.fromisoformat(shipment.eta)
        if shipment.status != ShipmentStatus.DELIVERED and eta < as_of:
            risks.append(
                _shipment_risk(
                    region_code=region_code,
                    rule_id="shipment.eta_passed_not_delivered",
                    shipment=shipment,
                    supplier_id=supplier_id,
                    supplier_name=supplier_name,
                    as_of=as_of,
                    title=f"Shipment {shipment.id} is past its expected arrival date",
                    explanation=(
                        f"Expected arrival {shipment.eta} is before the {DATASET_AS_OF_LABEL.lower()} "
                        f"{as_of.isoformat()}, and shipment {shipment.id} is not delivered. "
                        f"Purchase order {shipment.purchase_order_id}, supplier {supplier_name}, "
                        f"stored status {shipment.status.value}. "
                        "This compares stored dates. It does not predict a future delay."
                    ),
                    fingerprint_parts={
                        "eta": shipment.eta,
                        "as_of": as_of.isoformat(),
                        "purchase_order_id": shipment.purchase_order_id,
                        "status": shipment.status.value,
                        "supplier_id": supplier_id,
                    },
                )
            )
    return risks


def _shipment_risk(
    *,
    region_code: str,
    rule_id: str,
    shipment: Shipment,
    supplier_id: str,
    supplier_name: str,
    as_of: date,
    title: str,
    explanation: str,
    fingerprint_parts: dict[str, str],
) -> Risk:
    return Risk(
        id=_risk_id(region_code, rule_id, shipment.id),
        region_code=region_code,
        category=RULE_CATEGORY[rule_id],
        severity=RULE_SEVERITY[rule_id],
        title=title,
        explanation=explanation,
        severity_reason=SEVERITY_REASONS[rule_id],
        entity_ids=[shipment.id, shipment.purchase_order_id, supplier_id],
        evidence_lines=[
            f"Shipment {shipment.id}",
            f"Purchase order {shipment.purchase_order_id}",
            f"Supplier {supplier_name} ({supplier_id})",
            f"Status {shipment.status.value}",
            f"Expected arrival {shipment.eta}",
            f"{DATASET_AS_OF_LABEL} {as_of.isoformat()}",
        ],
        evidence_fingerprint=evidence_fingerprint(fingerprint_parts),
        rule_id=rule_id,
        dataset_as_of=as_of.isoformat(),
    )


def supplier_indicators(
    suppliers: list[Supplier],
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
) -> list[SupplierIndicator]:
    orders_by_supplier: dict[str, list[PurchaseOrder]] = {supplier.id: [] for supplier in suppliers}
    for order in orders:
        orders_by_supplier.setdefault(order.supplier_id, []).append(order)
    shipments_by_order = {shipment.purchase_order_id: shipment for shipment in shipments}
    chain_orders = len(orders)
    indicators: list[SupplierIndicator] = []
    for supplier in suppliers:
        supplier_orders = orders_by_supplier.get(supplier.id, [])
        linked = [
            shipments_by_order[order.id]
            for order in supplier_orders
            if order.id in shipments_by_order
        ]
        delayed = [shipment for shipment in linked if shipment.status == ShipmentStatus.DELAYED]
        if len(linked) >= MIN_SHIPMENTS_FOR_PROPORTION:
            proportion = f"{len(delayed)} of {len(linked)} linked shipments are delayed."
        else:
            proportion = (
                "Insufficient evidence "
                f"({len(linked)} linked shipments; at least {MIN_SHIPMENTS_FOR_PROPORTION} are required)."
            )
        indicators.append(
            SupplierIndicator(
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                delayed_shipment_count=len(delayed),
                linked_shipment_count=len(linked),
                delay_proportion_text=proportion,
                purchase_order_count=len(supplier_orders),
                order_share_text=(
                    f"{len(supplier_orders)} of {chain_orders} purchase orders in this supply chain."
                ),
                note=INDICATOR_NOTE,
            )
        )
    return indicators


def supplier_risks(
    region_code: str,
    suppliers: list[Supplier],
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
    as_of: date,
) -> list[Risk]:
    risks: list[Risk] = []
    orders_by_supplier: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        orders_by_supplier.setdefault(order.supplier_id, []).append(order)
    shipments_by_order = {shipment.purchase_order_id: shipment for shipment in shipments}
    chain_count = len(orders)
    for supplier in suppliers:
        supplier_orders = orders_by_supplier.get(supplier.id, [])
        linked = [
            shipments_by_order[order.id]
            for order in supplier_orders
            if order.id in shipments_by_order
        ]
        delayed = [shipment for shipment in linked if shipment.status == ShipmentStatus.DELAYED]
        if delayed:
            delayed_ids = sorted(shipment.id for shipment in delayed)
            rule_id = "supplier.delayed_shipment_present"
            risks.append(
                Risk(
                    id=_risk_id(region_code, rule_id, supplier.id),
                    region_code=region_code,
                    category=RULE_CATEGORY[rule_id],
                    severity=RULE_SEVERITY[rule_id],
                    title=f"{supplier.name} has a delayed shipment in this dataset",
                    explanation=(
                        f"{supplier.name} is linked to delayed shipment"
                        f"{'' if len(delayed_ids) == 1 else 's'} {', '.join(delayed_ids)}. "
                        "This is a count of stored delayed rows, not a reliability score."
                    ),
                    severity_reason=SEVERITY_REASONS[rule_id],
                    entity_ids=[supplier.id, *delayed_ids],
                    evidence_lines=[
                        f"Supplier {supplier.name} ({supplier.id})",
                        f"Delayed shipments {', '.join(delayed_ids)}",
                        f"Linked shipments {len(linked)}",
                    ],
                    evidence_fingerprint=evidence_fingerprint(
                        {"delayed_shipment_ids": ",".join(delayed_ids)}
                    ),
                    rule_id=rule_id,
                    dataset_as_of=as_of.isoformat(),
                )
            )
        share_meets_rule = (
            len(supplier_orders) >= MIN_ORDERS_FOR_CONCENTRATION
            and chain_count > 0
            and len(supplier_orders) * 2 >= chain_count
        )
        if share_meets_rule:
            rule_id = "supplier.order_share"
            order_ids = sorted(order.id for order in supplier_orders)
            risks.append(
                Risk(
                    id=_risk_id(region_code, rule_id, supplier.id),
                    region_code=region_code,
                    category=RULE_CATEGORY[rule_id],
                    severity=RULE_SEVERITY[rule_id],
                    title=f"{supplier.name} holds at least half of this chain's purchase orders",
                    explanation=(
                        f"{supplier.name} has {len(supplier_orders)} of {chain_count} "
                        "purchase orders in this supply chain, which meets the rule of "
                        "at least three orders and at least half of the chain. "
                        "This is not a statistical confidence score."
                    ),
                    severity_reason=SEVERITY_REASONS[rule_id],
                    entity_ids=[supplier.id, *order_ids],
                    evidence_lines=[
                        f"Supplier {supplier.name} ({supplier.id})",
                        f"Purchase orders {', '.join(order_ids)}",
                        f"Chain purchase orders {chain_count}",
                    ],
                    evidence_fingerprint=evidence_fingerprint(
                        {
                            "chain_order_count": str(chain_count),
                            "order_ids": ",".join(order_ids),
                        }
                    ),
                    rule_id=rule_id,
                    dataset_as_of=as_of.isoformat(),
                )
            )
    return risks


def detect_risks(
    *,
    region_code: str,
    inventory: list[InventoryRow],
    periods: list[DemandPeriod],
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
    suppliers: list[Supplier],
    as_of: date,
) -> tuple[list[Risk], list[SupplierIndicator]]:
    """Return risks and supplier indicators for one region. No cross-region data."""
    risks = [
        *inventory_risks(region_code, inventory, periods, as_of),
        *shipment_risks(region_code, shipments, orders, suppliers, as_of),
        *supplier_risks(region_code, suppliers, shipments, orders, as_of),
    ]
    risks.sort(key=lambda risk: risk.id)
    indicators = supplier_indicators(suppliers, shipments, orders)
    indicators.sort(key=lambda indicator: indicator.supplier_name)
    return risks, indicators


def reconcile_reviews(
    risks: list[Risk],
    reviews: dict[str, StoredReview],
) -> tuple[list[Risk], list[ReviewUpdate]]:
    """Keep a saved status only when the risk id and evidence fingerprint match.

    A reviewed or resolved status is not copied onto a risk whose evidence changed.
    That risk is reopened and marked for re-review.
    """
    updates: list[ReviewUpdate] = []
    reconciled: list[Risk] = []
    for risk in risks:
        stored = reviews.get(risk.id)
        current = risk.model_copy(deep=True)
        if stored is None:
            current.status = RiskStatus.OPEN
            current.re_review_note = ""
            reconciled.append(current)
            continue
        if stored.evidence_fingerprint == current.evidence_fingerprint:
            current.status = stored.status
            current.re_review_note = stored.re_review_note if stored.re_review_required else ""
            reconciled.append(current)
            continue
        if stored.status == RiskStatus.OPEN and not stored.re_review_required:
            current.status = RiskStatus.OPEN
            current.re_review_note = ""
            updates.append(
                ReviewUpdate(
                    risk_id=current.id,
                    rule_id=current.rule_id,
                    status=RiskStatus.OPEN,
                    evidence_fingerprint=current.evidence_fingerprint,
                    re_review_required=False,
                    re_review_note="",
                    write_audit=False,
                    previous_status=stored.status,
                )
            )
            reconciled.append(current)
            continue
        note = (
            "This risk needs re-review. The evidence changed after it was marked "
            f"{stored.status}. The earlier status was not kept."
        )
        current.status = RiskStatus.OPEN
        current.re_review_note = note
        updates.append(
            ReviewUpdate(
                risk_id=current.id,
                rule_id=current.rule_id,
                status=RiskStatus.OPEN,
                evidence_fingerprint=current.evidence_fingerprint,
                re_review_required=True,
                re_review_note=note,
                write_audit=True,
                previous_status=stored.status,
            )
        )
        reconciled.append(current)
    return reconciled, updates


def count_open(risks: list[Risk]) -> dict[str, int]:
    """Counts of open risks only. Reviewed and resolved rows stay in the register."""
    open_risks = [risk for risk in risks if risk.status == RiskStatus.OPEN]
    by_category = {category: 0 for category in (
        RiskCategory.INVENTORY,
        RiskCategory.SHIPMENT,
        RiskCategory.SUPPLIER,
    )}
    by_severity = {severity: 0 for severity in (RiskSeverity.ATTENTION, RiskSeverity.WATCH)}
    for risk in open_risks:
        by_category[risk.category] = by_category.get(risk.category, 0) + 1
        by_severity[risk.severity] = by_severity.get(risk.severity, 0) + 1
    return {
        "open": len(open_risks),
        "inventory": by_category[RiskCategory.INVENTORY],
        "shipment": by_category[RiskCategory.SHIPMENT],
        "supplier": by_category[RiskCategory.SUPPLIER],
        "attention": by_severity[RiskSeverity.ATTENTION],
        "watch": by_severity[RiskSeverity.WATCH],
    }
