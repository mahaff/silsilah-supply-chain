"""Investigation reports stay inside retrieved fields and one region."""

import sqlite3
from pathlib import Path

import pytest

from domain.metrics import build_metrics
from domain.risks import INSUFFICIENT_COVERAGE
from investigation.report import (
    ClaimRejected,
    InvestigationError,
    RetrievedField,
    StaleInvestigation,
    validate_claims,
)
from investigation.subjects import assert_fields_regional, assert_regional_text
from investigation.tools import ALLOWED_TOOLS, invoke_tool, run_fixed_plan
from investigation.workflow import (
    accept_investigation,
    dismiss_investigation,
    run_investigation,
)
from persistence.repository import RegionRepository

NOW = "2026-10-08T00:00:00+00:00"
RICE = "ksa:inventory.below_reorder:KSA-INV-002"
CARTON = "ksa:inventory.below_reorder:KSA-INV-004"
DELAYED = "ksa:shipment.delayed_status:KSA-SHP-003"
SUPPLIER = "ksa:supplier.delayed_shipment_present:KSA-SUP-002"
PAK_RISK = "pakistan:inventory.below_reorder:PAK-INV-001"

KSA_RISK_IDS = {
    "ksa:inventory.below_reorder:KSA-INV-002",
    "ksa:inventory.below_reorder:KSA-INV-004",
    "ksa:shipment.delayed_status:KSA-SHP-003",
    "ksa:shipment.eta_passed_not_delivered:KSA-SHP-002",
    "ksa:shipment.eta_passed_not_delivered:KSA-SHP-003",
    "ksa:supplier.delayed_shipment_present:KSA-SUP-002",
}
PAK_RISK_IDS = {
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


def test_rice_risk_cites_stock_and_coverage(regional_databases):
    report = run_investigation(_repo(regional_databases, "ksa"), "risk", RICE, now=NOW)
    on_hand = _claim(report, "inventory", "on_hand")
    reorder = _claim(report, "inventory", "reorder_point")
    coverage = _claim(report, "inventory", "coverage_text")
    assert on_hand.value == "15"
    assert reorder.value == "30"
    assert "not a predicted stockout date" in coverage.value
    assert all(claim.field != "probability" for claim in report.claims)
    assert "insufficient_demand_history" not in {gap.code for gap in report.gaps}


def test_carton_risk_does_not_invent_coverage(regional_databases):
    report = run_investigation(_repo(regional_databases, "ksa"), "risk", CARTON, now=NOW)
    coverage = _claim(report, "inventory", "coverage_text")
    assert coverage.value == INSUFFICIENT_COVERAGE
    assert not any(character.isdigit() for character in coverage.text)
    assert {gap.code for gap in report.gaps} == {"insufficient_demand_history"}
    assert report.gaps[0].text.startswith("Demand history is insufficient")


def test_delayed_shipment_is_not_given_a_probability(regional_databases):
    report = run_investigation(_repo(regional_databases, "ksa"), "risk", DELAYED, now=NOW)
    assert all(claim.field != "probability" for claim in report.claims)
    assert _claim(report, "shipment", "status").value == "delayed"
    assert "prediction_not_scored" in {gap.code for gap in report.gaps}


def test_ksa_estimate_keeps_rule_and_weak_holdout_separate(regional_databases):
    report = run_investigation(
        _repo(regional_databases, "ksa"), "estimate", "KSA-SHP-002", now=NOW
    )
    probability = _claim(report, "prediction", "probability")
    assert probability.value == "0.60"
    assert probability.evidence_kind == "ml_prediction"
    assert _claim(report, "prediction", "chronological_accuracy").value == "0.44"
    assert _claim(report, "prediction", "majority_accuracy").value == "0.56"
    summary = _claim(report, "prediction", "chronological_summary")
    assert "below the majority-class baseline" in summary.value
    assert "This is not a real-world forecast." in report.notices
    assert (
        "The model estimate and the deterministic rule are separate. "
        "The estimate does not confirm the rule."
    ) in report.notices
    rule = _claim(report, "related_rule", "rule_id")
    assert rule.evidence_kind == "deterministic_rule"
    assert rule.citation_id != probability.citation_id
    assert rule.value == "shipment.eta_passed_not_delivered"
    codes = {gap.code for gap in report.gaps}
    assert "model_below_baseline" in codes
    assert "estimate_alongside_known_condition" in codes
    blob = report.model_dump_json()
    for phrase in ("caused", "will be late", "definitely", "confirms the", "guaranteed"):
        assert phrase not in blob


def test_supplier_risk_does_not_use_model_history(regional_databases):
    report = run_investigation(_repo(regional_databases, "ksa"), "risk", SUPPLIER, now=NOW)
    assert "supplier_prior_late_rate" not in report.model_dump_json()
    assert "delay_proportion_withheld" in {gap.code for gap in report.gaps}
    assert "The predictive model history is not evidence for this supplier rule." in report.notices


def test_fabricated_claims_are_rejected(regional_databases):
    repository = _repo(regional_databases, "ksa")
    rice = run_investigation(repository, "risk", RICE, now=NOW)
    fields = _fields_from(rice)
    caused = rice.claims[0].model_copy(update={"text": "The supplier caused the delay."})
    with pytest.raises(ClaimRejected):
        validate_claims([caused, *rice.claims[1:]], fields)

    estimate = run_investigation(repository, "estimate", "KSA-SHP-002", now=NOW)
    estimate_fields = _fields_from(estimate)
    probability = _claim(estimate, "prediction", "probability")
    moved = probability.model_copy(
        update={
            "text": (
                "The model estimates a 0.44 probability of arriving after the expected date."
            )
        }
    )
    tampered = [
        moved if claim.citation_id == probability.citation_id else claim
        for claim in estimate.claims
    ]
    assert any(claim.value == "0.44" for claim in estimate.claims)
    with pytest.raises(ClaimRejected):
        validate_claims(tampered, estimate_fields)

    on_hand = _claim(rice, "inventory", "on_hand")
    reorder = _claim(rice, "inventory", "reorder_point")
    swapped = [
        reorder.model_copy(update={"value": on_hand.value, "text": f"Reorder point is {on_hand.value}."})
        if claim.citation_id == reorder.citation_id
        else claim
        for claim in rice.claims
    ]
    with pytest.raises(ClaimRejected):
        validate_claims(swapped, fields)

    planted = [
        on_hand.model_copy(update={"text": f"{on_hand.text} PAK-SHP-001"})
        if claim.citation_id == on_hand.citation_id
        else claim
        for claim in rice.claims
    ]
    with pytest.raises(ClaimRejected):
        validate_claims(planted, fields)


def test_tool_allow_list_rejects_writes():
    assert ALLOWED_TOOLS == (
        "get_subject",
        "get_linked_records",
        "get_supplier_indicator",
        "get_related_rules",
        "get_prediction_context",
    )
    with pytest.raises(InvestigationError):
        run_fixed_plan(("get_subject", "set_risk_status"))
    called = {"count": 0}

    def set_risk_status():
        called["count"] += 1

    with pytest.raises(InvestigationError):
        invoke_tool("set_risk_status", set_risk_status)
    assert called["count"] == 0
    source = "\n".join(path.read_text() for path in Path("investigation").glob("*.py"))
    for banned in ("langchain", "langgraph", "joblib", "pickle", "import llm", "httpx", "openai"):
        assert banned not in source


def test_draft_writes_no_audit_and_decisions_write_one(regional_databases):
    repository = _repo(regional_databases, "ksa")
    before = len(repository.list_audit_events())
    rice = run_investigation(repository, "risk", RICE, now=NOW)
    assert len(repository.list_audit_events()) == before
    accept_investigation(repository, rice.id, now=NOW)
    carton = run_investigation(repository, "risk", CARTON, now=NOW)
    dismiss_investigation(repository, carton.id, now=NOW)
    audits = repository.list_audit_events()
    assert len(audits) == before + 2
    accepted = [row for row in audits if row.action == "investigation_accepted"]
    dismissed = [row for row in audits if row.action == "investigation_dismissed"]
    assert len(accepted) == 1
    assert len(dismissed) == 1
    assert accepted[0].actor == "local_user"
    assert accepted[0].evidence_kind == "human_decision"
    assert accepted[0].risk_id == RICE
    assert accepted[0].rule_id == "inventory.below_reorder"
    assert "No operational record was changed." in accepted[0].summary
    assert dismissed[0].risk_id == CARTON
    assert "No operational record was changed." in dismissed[0].summary
    with pytest.raises(InvestigationError):
        accept_investigation(repository, rice.id, now=NOW)
    assert len(repository.list_audit_events()) == before + 2
    assert not any(row.action == "risk_status_changed" for row in repository.list_audit_events())


def test_accept_and_dismiss_do_not_change_operations(regional_databases):
    ksa = _repo(regional_databases, "ksa")
    pakistan = _repo(regional_databases, "pakistan")
    before = _operations(ksa)
    assert before["metrics"] == {
        "suppliers": 4,
        "products": 6,
        "open_purchase_orders": 3,
        "shipments_in_transit": 1,
        "delayed_shipments": 1,
        "low_stock_lines": 2,
    }
    rice = run_investigation(ksa, "risk", RICE, now=NOW)
    accept_investigation(ksa, rice.id, now=NOW)
    carton = run_investigation(ksa, "risk", CARTON, now=NOW)
    dismiss_investigation(ksa, carton.id, now=NOW)
    estimate = run_investigation(ksa, "estimate", "KSA-SHP-002", now=NOW)
    accepted = accept_investigation(ksa, estimate.id, now=NOW)
    assert accepted.subject_kind == "estimate"
    decision = [
        row
        for row in ksa.list_audit_events()
        if row.action == "investigation_accepted" and row.summary.startswith("Accepted investigation")
        and estimate.id in row.summary
    ]
    assert len(decision) == 1
    assert decision[0].risk_id is None
    assert decision[0].rule_id is None
    assert _operations(ksa) == before
    assert ksa.list_reviews() == {}
    pak_metrics = _metric_map(pakistan)
    assert pak_metrics["open_purchase_orders"] == 2
    assert pak_metrics["shipments_in_transit"] == 0
    assert pak_metrics["delayed_shipments"] == 2
    assert pak_metrics["low_stock_lines"] == 3


def test_stale_draft_cannot_be_decided(regional_databases):
    repository = _repo(regional_databases, "ksa")
    report = run_investigation(repository, "risk", RICE, now=NOW)
    before = len(repository.list_audit_events())
    connection = sqlite3.connect(regional_databases["ksa"])
    connection.execute(
        "UPDATE investigations SET evidence_fingerprint = 'tampered' WHERE id = ?",
        (report.id,),
    )
    connection.commit()
    connection.close()
    with pytest.raises(StaleInvestigation):
        accept_investigation(repository, report.id, now=NOW)
    stored = repository.get_investigation(report.id)
    assert stored is not None
    assert stored["status"] == "stale"
    assert len(repository.list_audit_events()) == before
    with pytest.raises(StaleInvestigation):
        dismiss_investigation(repository, report.id, now=NOW)
    assert len(repository.list_audit_events()) == before


def test_regions_do_not_share_investigations(regional_databases):
    ksa = _repo(regional_databases, "ksa")
    pakistan = _repo(regional_databases, "pakistan")
    with pytest.raises(InvestigationError):
        run_investigation(ksa, "risk", PAK_RISK, now=NOW)
    assert ksa.list_investigation_ids() == []
    with pytest.raises(ValueError):
        ksa.save_investigation_draft(
            investigation_id="inv:pakistan:risk:aaaaaaaaaaaaaaaa",
            subject_kind="risk",
            subject_id=PAK_RISK,
            evidence_fingerprint="subject_id=" + PAK_RISK,
            report_json="{}",
            now=NOW,
        )
    assert ksa.list_investigation_ids() == []
    ksa_report = run_investigation(ksa, "risk", RICE, now=NOW)
    pak_report = run_investigation(pakistan, "risk", PAK_RISK, now=NOW)
    assert ksa_report.id not in pakistan.list_investigation_ids()
    assert pak_report.id not in ksa.list_investigation_ids()
    with pytest.raises(InvestigationError):
        assert_regional_text("ksa", "see PAK-SHP-001")
    foreign = RetrievedField(
        source="shipment",
        record_id="KSA-SHP-002",
        field="status",
        value="in_transit PAK-SHP-001",
        evidence_kind="database_fact",
    )
    with pytest.raises(InvestigationError):
        assert_fields_regional("ksa", [foreign])


def test_unscored_estimate_is_refused(regional_databases):
    repository = _repo(regional_databases, "ksa")
    with pytest.raises(InvestigationError, match="Only a scored estimate"):
        run_investigation(repository, "estimate", "KSA-SHP-003", now=NOW)
    assert repository.list_investigation_ids() == []
    pakistan = _repo(regional_databases, "pakistan")
    with pytest.raises(InvestigationError, match="Only a scored estimate"):
        run_investigation(pakistan, "estimate", "PAK-SHP-001", now=NOW)
    assert pakistan.list_investigation_ids() == []


def test_repeating_an_investigation_does_not_reset_it(regional_databases):
    repository = _repo(regional_databases, "ksa")
    before = len(repository.list_audit_events())
    first = run_investigation(repository, "risk", RICE, now=NOW)
    accept_investigation(repository, first.id, now=NOW)
    second = run_investigation(repository, "risk", RICE, now=NOW)
    assert second.id == first.id
    assert second.status == "accepted"
    assert repository.list_investigation_ids() == [first.id]
    assert len(repository.list_audit_events()) == before + 1


def test_seed_starts_with_an_empty_investigation_table(regional_databases):
    connection = sqlite3.connect(regional_databases["ksa"])
    try:
        assert connection.execute("SELECT COUNT(*) FROM investigations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM shipments").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM shipment_history").fetchone()[0] == 48
    finally:
        connection.close()
    connection = sqlite3.connect(regional_databases["pakistan"])
    try:
        assert connection.execute("SELECT COUNT(*) FROM investigations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM shipment_history").fetchone()[0] == 48
    finally:
        connection.close()


def _repo(regional_databases, region_code: str) -> RegionRepository:
    return RegionRepository(region_code, database_path=regional_databases[region_code])


def _claim(report, source: str, field: str):
    matches = [
        claim for claim in report.claims if claim.source == source and claim.field == field
    ]
    assert len(matches) == 1
    return matches[0]


def _fields_from(report) -> list[RetrievedField]:
    return [
        RetrievedField(
            source=claim.source,
            record_id=claim.record_id,
            field=claim.field,
            value=claim.value,
            evidence_kind=claim.evidence_kind,
        )
        for claim in report.claims
    ]


def _operations(repository: RegionRepository) -> dict:
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    _name, risks, _indicators = repository.detected_inputs()
    shipments = repository.list_shipments(chain_id)
    inventory = repository.list_inventory(chain_id)
    orders = repository.list_purchase_orders(chain_id)
    expected = KSA_RISK_IDS if repository.config.region_code == "ksa" else PAK_RISK_IDS
    assert {risk.id for risk in risks} == expected
    return {
        "metrics": _metric_map(repository),
        "shipments": tuple(sorted((row.id, row.status.value) for row in shipments)),
        "inventory": tuple(sorted((row.id, row.on_hand) for row in inventory)),
        "orders": tuple(sorted((row.id, row.status.value) for row in orders)),
        "reviews": tuple(sorted(repository.list_reviews())),
    }


def _metric_map(repository: RegionRepository) -> dict[str, int]:
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
