"""Read-only tools. The plan is fixed and nothing here writes."""

from dataclasses import dataclass

from domain.models import InventoryRow, Shipment, Supplier
from domain.risks import (
    Risk,
    SupplierIndicator,
    estimate_coverage,
    evidence_fingerprint,
)
from investigation.report import InvestigationError, RetrievedField
from investigation.subjects import assert_fields_regional, assert_subject
from persistence.repository import RegionRepository
from prediction.model import PredictionSnapshot, build_prediction_snapshot

ALLOWED_TOOLS: tuple[str, ...] = (
    "get_subject",
    "get_linked_records",
    "get_supplier_indicator",
    "get_related_rules",
    "get_prediction_context",
)

UNSCORED_ESTIMATE = (
    "Only a scored estimate can be investigated. This shipment has no probability."
)


@dataclass
class Gathered:
    fields: list[RetrievedField]
    risk_fingerprint: str | None
    subject_rule_id: str | None


def run_fixed_plan(names: tuple[str, ...]) -> None:
    """Reject any tool list other than the one fixed plan."""
    if tuple(names) != ALLOWED_TOOLS:
        raise InvestigationError("The investigation uses one fixed read-only tool order.")


def invoke_tool(name: str, fn, /, *args, **kwargs):
    """Call fn only after the name is on the allow-list."""
    if name not in ALLOWED_TOOLS:
        raise InvestigationError(f"{name} is not an allowed investigation tool.")
    return fn(*args, **kwargs)


def gather(repository: RegionRepository, kind: str, subject_id: str) -> Gathered:
    """Run the five tools once, in order, and return their fields."""
    assert_subject(repository.config.region_code, kind, subject_id)
    run_fixed_plan(ALLOWED_TOOLS)
    bundle = _load(repository)
    risk = _risk_by_id(bundle["risks"], subject_id) if kind == "risk" else None
    if kind == "risk" and risk is None:
        raise InvestigationError("That risk is not produced by this region's current rules.")
    shipment = _shipment_for(bundle, kind, subject_id, risk)
    if kind == "estimate" and shipment is None:
        raise InvestigationError("That shipment is not in this region.")
    if kind == "estimate":
        _require_scored(bundle, shipment.id)
    fields: list[RetrievedField] = []
    fields.extend(invoke_tool("get_subject", _get_subject, bundle, risk))
    fields.extend(invoke_tool("get_linked_records", _get_linked_records, bundle, kind, risk, shipment))
    fields.extend(
        invoke_tool("get_supplier_indicator", _get_supplier_indicator, bundle, kind, risk, shipment)
    )
    fields.extend(invoke_tool("get_related_rules", _get_related_rules, bundle, kind, subject_id, risk, shipment))
    fields.extend(
        invoke_tool(
            "get_prediction_context",
            _get_prediction_context,
            bundle,
            kind,
            risk,
            shipment,
        )
    )
    assert_fields_regional(repository.config.region_code, fields)
    return Gathered(
        fields=fields,
        risk_fingerprint=None if risk is None else risk.evidence_fingerprint,
        subject_rule_id=None if risk is None else risk.rule_id,
    )


def investigation_fingerprint(kind: str, subject_id: str, gathered: Gathered) -> str:
    """Fingerprint the fields that would make this draft stale."""
    parts: dict[str, str] = {
        "subject_id": subject_id,
        "subject_kind": kind,
    }
    as_of = _only_value(gathered.fields, "app_meta", "dataset_as_of")
    if as_of is not None:
        parts["dataset_as_of"] = as_of
    if gathered.risk_fingerprint is not None:
        parts["risk_evidence_fingerprint"] = gathered.risk_fingerprint
    coverage = _only_value(gathered.fields, "inventory", "coverage_text")
    if coverage is not None:
        parts["coverage_text"] = coverage
    status = _only_value(gathered.fields, "shipment", "status")
    eta = _only_value(gathered.fields, "shipment", "eta")
    if status is not None:
        parts["shipment_status"] = status
    if eta is not None:
        parts["shipment_eta"] = eta
    delayed = _only_value(gathered.fields, "indicator", "delayed_shipment_count")
    proportion = _only_value(gathered.fields, "indicator", "delay_proportion_text")
    if delayed is not None:
        parts["delayed_shipment_count"] = delayed
    if proportion is not None:
        parts["delay_proportion_text"] = proportion
    probability = _only_value(gathered.fields, "prediction", "probability")
    if probability is not None:
        parts["probability"] = probability
        summary = _only_value(gathered.fields, "prediction", "chronological_summary")
        if summary is not None:
            parts["chronological_summary"] = summary
    return evidence_fingerprint(parts)


def _only_value(fields: list[RetrievedField], source: str, field_name: str) -> str | None:
    matches = [item for item in fields if item.source == source and item.field == field_name]
    if len(matches) > 1:
        raise InvestigationError(f"Expected one {source}.{field_name} field.")
    return None if not matches else matches[0].value


def _load(repository: RegionRepository) -> dict:
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    _display_name, risks, indicators = repository.detected_inputs()
    return {
        "region_code": repository.config.region_code,
        "risks": risks,
        "indicators": indicators,
        "inventory": repository.list_inventory(chain_id),
        "periods": repository.list_demand(chain_id),
        "shipments": repository.list_shipments(chain_id),
        "orders": repository.list_purchase_orders(chain_id),
        "suppliers": repository.list_suppliers(chain_id),
        "history": repository.list_shipment_history(chain_id),
        "as_of": repository.dataset_as_of(),
        "snapshot": None,
    }


def _risk_by_id(risks: list[Risk], risk_id: str) -> Risk | None:
    return next((risk for risk in risks if risk.id == risk_id), None)


def _shipment_for(
    bundle: dict,
    kind: str,
    subject_id: str,
    risk: Risk | None,
) -> Shipment | None:
    shipment_id = subject_id if kind == "estimate" else None
    if risk is not None and risk.category == "shipment":
        shipment_id = risk.entity_ids[0]
    if shipment_id is None:
        return None
    return next((row for row in bundle["shipments"] if row.id == shipment_id), None)


def _field(source: str, record_id: str, field_name: str, value: str) -> RetrievedField:
    from investigation.report import FIELD_KINDS

    return RetrievedField(
        source=source,
        record_id=record_id,
        field=field_name,
        value=value,
        evidence_kind=FIELD_KINDS[(source, field_name)],
    )


def _get_subject(bundle: dict, risk: Risk | None) -> list[RetrievedField]:
    fields = [_field("app_meta", "dataset_as_of", "dataset_as_of", bundle["as_of"])]
    if risk is None:
        return fields
    fields.append(_field("risk", risk.id, "explanation", risk.explanation))
    fields.append(_field("risk", risk.id, "rule_id", risk.rule_id))
    return fields


def _get_linked_records(
    bundle: dict,
    kind: str,
    risk: Risk | None,
    shipment: Shipment | None,
) -> list[RetrievedField]:
    if risk is not None and risk.category == "inventory":
        row = _inventory_row(bundle["inventory"], risk.entity_ids[0])
        coverage = estimate_coverage(
            row.on_hand,
            row.warehouse_id,
            row.product_id,
            bundle["periods"],
        )
        return [
            _field("inventory", row.id, "on_hand", str(row.on_hand)),
            _field("inventory", row.id, "reorder_point", str(row.reorder_point)),
            _field("inventory", row.id, "product_name", row.product_name),
            _field("inventory", row.id, "warehouse_name", row.warehouse_name),
            _field("inventory", row.id, "coverage_text", coverage.text),
        ]
    if shipment is None:
        supplier = _supplier_for(bundle, kind, risk, shipment)
        if supplier is None:
            return []
        return _supplier_fields(supplier)
    fields = _shipment_fields(shipment)
    supplier = _supplier_for(bundle, kind, risk, shipment)
    if supplier is not None:
        fields.extend(_supplier_fields(supplier))
    return fields


def _inventory_row(rows: list[InventoryRow], inventory_id: str) -> InventoryRow:
    match = next((row for row in rows if row.id == inventory_id), None)
    if match is None:
        raise InvestigationError("That inventory row is not in this region.")
    return match


def _shipment_fields(shipment: Shipment) -> list[RetrievedField]:
    departed = shipment.departed_on if shipment.departed_on else "not recorded"
    return [
        _field("shipment", shipment.id, "id", shipment.id),
        _field("shipment", shipment.id, "status", shipment.status.value),
        _field("shipment", shipment.id, "eta", shipment.eta),
        _field("shipment", shipment.id, "departed_on", departed),
        _field("shipment", shipment.id, "purchase_order_id", shipment.purchase_order_id),
    ]


def _supplier_fields(supplier: Supplier) -> list[RetrievedField]:
    return [
        _field("supplier", supplier.id, "id", supplier.id),
        _field("supplier", supplier.id, "name", supplier.name),
    ]


def _supplier_for(
    bundle: dict,
    kind: str,
    risk: Risk | None,
    shipment: Shipment | None,
) -> Supplier | None:
    supplier_id = None
    if risk is not None and risk.category == "supplier":
        supplier_id = risk.entity_ids[0]
    elif shipment is not None:
        order = next(
            (row for row in bundle["orders"] if row.id == shipment.purchase_order_id),
            None,
        )
        if order is None:
            raise InvestigationError("That purchase order is not in this region.")
        supplier_id = order.supplier_id
    if supplier_id is None:
        return None
    match = next((row for row in bundle["suppliers"] if row.id == supplier_id), None)
    if match is None:
        raise InvestigationError("That supplier is not in this region.")
    return match


def _get_supplier_indicator(
    bundle: dict,
    kind: str,
    risk: Risk | None,
    shipment: Shipment | None,
) -> list[RetrievedField]:
    supplier = _supplier_for(bundle, kind, risk, shipment)
    if supplier is None:
        return []
    indicator = next(
        (row for row in bundle["indicators"] if row.supplier_id == supplier.id),
        None,
    )
    if indicator is None:
        raise InvestigationError("That supplier indicator is not in this region.")
    return _indicator_fields(indicator)


def _indicator_fields(indicator: SupplierIndicator) -> list[RetrievedField]:
    record_id = indicator.supplier_id
    return [
        _field("indicator", record_id, "delayed_shipment_count", str(indicator.delayed_shipment_count)),
        _field("indicator", record_id, "linked_shipment_count", str(indicator.linked_shipment_count)),
        _field("indicator", record_id, "delay_proportion_text", indicator.delay_proportion_text),
        _field("indicator", record_id, "order_share_text", indicator.order_share_text),
        _field("indicator", record_id, "note", indicator.note),
    ]


def _get_related_rules(
    bundle: dict,
    kind: str,
    subject_id: str,
    risk: Risk | None,
    shipment: Shipment | None,
) -> list[RetrievedField]:
    if risk is not None:
        anchors = set(risk.entity_ids)
        exclude = risk.id
    elif shipment is not None:
        anchors = {shipment.id}
        exclude = ""
    else:
        anchors = {subject_id}
        exclude = ""
    fields: list[RetrievedField] = []
    for other in bundle["risks"]:
        if other.id == exclude:
            continue
        if anchors.intersection(other.entity_ids):
            fields.append(_field("related_rule", other.id, "rule_id", other.rule_id))
    fields.sort(key=lambda item: item.record_id)
    return fields


def _get_prediction_context(
    bundle: dict,
    kind: str,
    risk: Risk | None,
    shipment: Shipment | None,
) -> list[RetrievedField]:
    shipment_subject = kind == "estimate" or (risk is not None and risk.category == "shipment")
    if not shipment_subject or shipment is None:
        return []
    if kind == "estimate":
        _require_scored(bundle, shipment.id)
    snapshot = _snapshot(bundle)
    estimate = next(
        (item for item in snapshot.estimates if item.shipment_id == shipment.id),
        None,
    )
    if estimate is None or not estimate.scored:
        return [_field("prediction", shipment.id, "scored", "no")]
    fields = [
        _field("prediction", shipment.id, "scored", "yes"),
        _field("prediction", shipment.id, "probability", f"{estimate.probability:.2f}"),
    ]
    chronological = snapshot.chronological
    fields.append(
        _field(
            "prediction",
            "chronological",
            "chronological_summary",
            chronological.summary(),
        )
    )
    if (
        chronological.available
        and chronological.accuracy is not None
        and chronological.majority_accuracy is not None
    ):
        fields.append(
            _field(
                "prediction",
                "chronological",
                "chronological_accuracy",
                f"{chronological.accuracy:.2f}",
            )
        )
        fields.append(
            _field(
                "prediction",
                "chronological",
                "majority_accuracy",
                f"{chronological.majority_accuracy:.2f}",
            )
        )
        below = "yes" if chronological.accuracy < chronological.majority_accuracy else "no"
        fields.append(_field("prediction", "chronological", "below_baseline", below))
    for contribution in sorted(estimate.contributions, key=lambda item: item.feature):
        fields.append(
            _field(
                "prediction",
                contribution.feature,
                "contribution_sentence",
                contribution.sentence,
            )
        )
    return fields


def _require_scored(bundle: dict, shipment_id: str) -> None:
    snapshot = _snapshot(bundle)
    estimate = next(
        (item for item in snapshot.estimates if item.shipment_id == shipment_id),
        None,
    )
    if estimate is None or not estimate.scored or estimate.probability is None:
        raise InvestigationError(UNSCORED_ESTIMATE)


def _snapshot(bundle: dict) -> PredictionSnapshot:
    if bundle["snapshot"] is None:
        bundle["snapshot"] = build_prediction_snapshot(
            history=bundle["history"],
            suppliers=bundle["suppliers"],
            shipments=bundle["shipments"],
            orders=bundle["orders"],
            dataset_as_of=bundle["as_of"],
        )
    return bundle["snapshot"]
