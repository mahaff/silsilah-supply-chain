"""Predictive demonstration: labels, leakage controls, and regional models."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from domain.metrics import build_metrics
from domain.models import (
    OrderStatus,
    PurchaseOrder,
    Shipment,
    ShipmentHistoryTrip,
    ShipmentStatus,
    Supplier,
    SupplierStatus,
)
from persistence.repository import RegionRepository
from persistence.seed import _validate_shipment_history
from prediction.explain import explain_contributions, probability_sentence
from prediction.features import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURE_NAMES,
    build_feature_table,
    feature_matrix,
    is_late,
)
from prediction.model import (
    RANDOM_STATE,
    EvaluationReport,
    build_prediction_snapshot,
    chronological_holdout,
    fit_scoring_model,
    make_estimator,
)

BANNED_PHRASES = (
    "supplier caused the delay",
    "this supplier will be late",
    "the shipment will definitely be delayed",
    "caused the delay",
    "definitely",
    "will be late",
)

KSA_RISK_IDS = {
    "ksa:inventory.below_reorder:KSA-INV-002",
    "ksa:inventory.below_reorder:KSA-INV-004",
    "ksa:shipment.delayed_status:KSA-SHP-003",
    "ksa:shipment.eta_passed_not_delivered:KSA-SHP-002",
    "ksa:shipment.eta_passed_not_delivered:KSA-SHP-003",
    "ksa:supplier.delayed_shipment_present:KSA-SUP-002",
}

PAKISTAN_RISK_IDS = {
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


def test_late_label_uses_arrival_after_the_expected_date():
    eta = date(2026, 5, 2)
    assert is_late(date(2026, 5, 3), eta) is True
    assert is_late(eta, eta) is False
    assert is_late(date(2026, 5, 1), eta) is False
    trips = [
        _trip("KSA-HST-001", "KSA-SUP-001", date(2026, 4, 1), date(2026, 4, 5), date(2026, 4, 5)),
        _trip("KSA-HST-002", "KSA-SUP-001", date(2026, 4, 10), date(2026, 4, 14), date(2026, 4, 16)),
        _trip("KSA-HST-003", "KSA-SUP-001", date(2026, 4, 20), date(2026, 4, 24), date(2026, 4, 24)),
        _trip("KSA-HST-004", "KSA-SUP-001", date(2026, 5, 1), date(2026, 5, 6), date(2026, 5, 6)),
    ]
    rows = {row.trip_id: row for row in build_feature_table(trips, {"KSA-SUP-001": 5})}
    assert rows["KSA-HST-004"].included is True
    assert rows["KSA-HST-004"].late == 0
    late_copy = [_flip_arrival(trip) if trip.id == "KSA-HST-004" else trip for trip in trips]
    relabeled = {row.trip_id: row for row in build_feature_table(late_copy, {"KSA-SUP-001": 5})}
    assert relabeled["KSA-HST-004"].late == 1
    assert relabeled["KSA-HST-004"].values == rows["KSA-HST-004"].values


def test_prior_history_excludes_the_current_trip_and_later_trips():
    trips = [
        _trip("KSA-HST-001", "KSA-SUP-001", date(2026, 4, 1), date(2026, 4, 4), date(2026, 4, 6)),
        _trip("KSA-HST-002", "KSA-SUP-001", date(2026, 4, 10), date(2026, 4, 14), date(2026, 4, 14)),
        _trip("KSA-HST-003", "KSA-SUP-001", date(2026, 4, 20), date(2026, 4, 24), date(2026, 4, 26)),
        _trip("KSA-HST-004", "KSA-SUP-001", date(2026, 5, 1), date(2026, 5, 5), date(2026, 5, 5)),
        _trip("KSA-HST-005", "KSA-SUP-001", date(2026, 5, 1), date(2026, 5, 8), date(2026, 5, 10)),
        _trip("KSA-HST-006", "KSA-SUP-001", date(2026, 5, 20), date(2026, 5, 24), date(2026, 5, 28)),
    ]
    lead = {"KSA-SUP-001": 5}
    rows = {row.trip_id: row for row in build_feature_table(trips, lead)}
    current = rows["KSA-HST-004"]
    same_day = rows["KSA-HST-005"]
    assert current.included and same_day.included
    assert current.values["supplier_prior_trip_count"] == 3
    assert same_day.values["supplier_prior_trip_count"] == 3
    assert current.values["supplier_prior_late_rate"] == pytest.approx(2 / 3)
    assert same_day.values["supplier_prior_late_rate"] == pytest.approx(2 / 3)
    assert "status" not in current.values
    assert "arrived_on" not in current.values
    assert set(current.values) == set(FEATURE_COLUMNS)
    assert not set(current.values) & FORBIDDEN_FEATURE_NAMES

    with_later_flip = [
        _flip_arrival(trip) if trip.id == "KSA-HST-006" else trip for trip in trips
    ]
    later = {row.trip_id: row for row in build_feature_table(with_later_flip, lead)}
    assert later["KSA-HST-004"].values == current.values
    assert later["KSA-HST-005"].values == same_day.values
    assert later["KSA-HST-006"].values == rows["KSA-HST-006"].values
    assert later["KSA-HST-006"].late != rows["KSA-HST-006"].late

    with_earlier_flip = [
        _flip_arrival(trip) if trip.id == "KSA-HST-001" else trip for trip in trips
    ]
    earlier = {row.trip_id: row for row in build_feature_table(with_earlier_flip, lead)}
    assert earlier["KSA-HST-004"].values["supplier_prior_late_rate"] == pytest.approx(1 / 3)


def test_feature_matrix_rejects_rows_outside_the_allow_list():
    included = _feature_row("KSA-HST-001", late=1)
    matrix = feature_matrix([included])
    assert matrix == [[included.values[name] for name in FEATURE_COLUMNS]]
    excluded = included.model_copy(update={"included": False, "values": {}})
    with pytest.raises(ValueError, match="excluded"):
        feature_matrix([excluded])
    leaked = included.model_copy(
        update={"values": {**included.values, "status": 1.0}}
    )
    with pytest.raises(ValueError, match="allow-list"):
        feature_matrix([leaked])


def test_seeded_chronological_holdout_is_the_primary_time_ordered_evaluation(regional_databases):
    snapshot = _snapshot("ksa", regional_databases["ksa"])
    report = snapshot.chronological
    assert report.name == "chronological"
    assert report.role == "primary"
    assert report.available is True
    assert report.train_rows == 27
    assert report.test_rows == 9
    assert report.train_late == 13
    assert report.train_on_time == 14
    assert report.test_late == 4
    assert report.test_on_time == 5
    _assert_metric_bounds(report)
    history, lead = _history_and_lead("ksa", regional_databases["ksa"])
    rows = {row.trip_id: row for row in build_feature_table(history, lead)}
    train_dates = [rows[trip_id].departed_on for trip_id in report.train_ids]
    test_dates = [rows[trip_id].departed_on for trip_id in report.test_ids]
    assert max(train_dates) <= min(test_dates)
    assert set(report.train_ids).isdisjoint(report.test_ids)
    latest_test_id = max(report.test_ids, key=lambda trip_id: rows[trip_id].departed_on)
    mutated = [
        _flip_arrival(trip) if trip.id == latest_test_id else trip for trip in history
    ]
    changed = {row.trip_id: row for row in build_feature_table(mutated, lead)}
    for trip_id in report.train_ids:
        assert changed[trip_id].values == rows[trip_id].values
        assert changed[trip_id].late == rows[trip_id].late
    assert changed[latest_test_id].values == rows[latest_test_id].values
    assert changed[latest_test_id].late != rows[latest_test_id].late


def test_random_split_repeats_with_the_fixed_seed(regional_databases):
    first = _snapshot("ksa", regional_databases["ksa"])
    second = _snapshot("ksa", regional_databases["ksa"])
    assert first.random_split.name == "random"
    assert first.random_split.role == "secondary"
    assert first.random_split.available is True
    assert first.random_split.train_rows == 27
    assert first.random_split.test_rows == 9
    assert first.random_split.train_late >= 1
    assert first.random_split.test_late >= 1
    assert first.random_split.test_on_time >= 1
    _assert_metric_bounds(first.random_split)
    assert first.random_split.train_ids == second.random_split.train_ids
    assert first.random_split.test_ids == second.random_split.test_ids
    assert first.random_split.accuracy == second.random_split.accuracy
    assert first.coefficients == second.coefficients
    assert first.chronological.summary() != first.random_split.summary()
    assert make_estimator().named_steps["model"].random_state == RANDOM_STATE


def test_insufficient_history_refuses_to_train_or_score():
    history = _series("KSA-SUP-001", 8, late_until=4)
    shipment = _operational(
        "KSA-SHP-900",
        ShipmentStatus.IN_TRANSIT,
        departed="2026-08-01",
        eta="2026-08-10",
    )
    snapshot = build_prediction_snapshot(
        history=history,
        suppliers=[_supplier()],
        shipments=[shipment],
        orders=[_order()],
        dataset_as_of="2026-10-01",
    )
    assert snapshot.trained is False
    assert snapshot.chronological.available is False
    assert snapshot.chronological.accuracy is None
    assert snapshot.random_split.available is False
    assert snapshot.random_split.accuracy is None
    assert "No probability is shown." in snapshot.refusal_reason
    assert snapshot.estimates[0].scored is False
    assert snapshot.estimates[0].probability is None
    assert snapshot.estimates[0].contributions == []

    mostly_on_time = _series("KSA-SUP-001", 30, late_until=5)
    refused = build_prediction_snapshot(
        history=mostly_on_time,
        suppliers=[_supplier()],
        shipments=[],
        orders=[],
        dataset_as_of="2026-10-01",
    )
    assert refused.trained is False
    assert "at least 6" in refused.refusal_reason


def test_one_class_tail_refuses_the_chronological_holdout_without_inventing_metrics():
    history = []
    for index in range(30):
        departed = date(2026, 1, 1) + timedelta(days=index)
        eta = departed + timedelta(days=4)
        late = index < 24 and index % 2 == 0
        arrived = eta + timedelta(days=2 if late else 0)
        history.append(_trip(f"KSA-HST-{index:03d}", "KSA-SUP-001", departed, eta, arrived))
    rows = build_feature_table(history, {"KSA-SUP-001": 5})
    train, test, reason = chronological_holdout(rows)
    assert train == []
    assert test == []
    assert "not reported" in reason
    snapshot = build_prediction_snapshot(
        history=history,
        suppliers=[_supplier()],
        shipments=[
            _operational(
                "KSA-SHP-901",
                ShipmentStatus.IN_TRANSIT,
                departed="2026-03-15",
                eta="2026-03-20",
            )
        ],
        orders=[_order()],
        dataset_as_of="2026-10-01",
    )
    assert snapshot.trained is True
    assert snapshot.chronological.available is False
    assert snapshot.chronological.accuracy is None
    assert snapshot.chronological.roc_auc is None
    assert "not reported" in snapshot.chronological.refusal_reason
    assert snapshot.random_split.available is True
    assert snapshot.estimates[0].scored is True


def test_balanced_class_weight_changes_the_coefficients():
    rows = []
    for index in range(36):
        rows.append(
            _feature_row(
                f"KSA-HST-{index:03d}",
                late=1 if index < 8 else 0,
                departed=date(2026, 1, 1) + timedelta(days=index),
                lead=float(4 + (index % 5)),
                transit=float(3 + (index % 6)),
                same=float(index % 2),
                rate=(index % 4) / 4,
                prior=float(3 + index),
            )
        )
    balanced = fit_scoring_model(rows, balanced=True)
    plain = fit_scoring_model(rows, balanced=False)
    assert balanced is not None and plain is not None
    assert balanced.named_steps["model"].class_weight == "balanced"
    assert plain.named_steps["model"].class_weight is None
    assert not np.allclose(
        balanced.named_steps["model"].coef_,
        plain.named_steps["model"].coef_,
    )
    again = fit_scoring_model(rows, balanced=True)
    assert np.allclose(
        balanced.named_steps["model"].coef_,
        again.named_steps["model"].coef_,
    )


def test_regions_do_not_share_history_or_coefficients(regional_databases):
    ksa = _snapshot("ksa", regional_databases["ksa"])
    pakistan = _snapshot("pakistan", regional_databases["pakistan"])
    ksa_history, _lead = _history_and_lead("ksa", regional_databases["ksa"])
    pakistan_history, _pakistan_lead = _history_and_lead("pakistan", regional_databases["pakistan"])
    assert {trip.supplier_id[:4] for trip in ksa_history} == {"KSA-"}
    assert {trip.supplier_id[:4] for trip in pakistan_history} == {"PAK-"}
    assert {trip.id for trip in ksa_history}.isdisjoint({trip.id for trip in pakistan_history})
    assert ksa.trained and pakistan.trained
    assert len(ksa.coefficients) == len(FEATURE_COLUMNS)
    assert not np.allclose(ksa.coefficients, pakistan.coefficients)
    assert all(estimate.shipment_id.startswith("KSA-") for estimate in ksa.estimates)
    assert all(estimate.shipment_id.startswith("PAK-") for estimate in pakistan.estimates)
    with pytest.raises(ValueError, match="mixes Saudi Arabia and Pakistan"):
        build_prediction_snapshot(
            history=[*ksa_history, pakistan_history[0]],
            suppliers=[_supplier()],
            shipments=[],
            orders=[],
            dataset_as_of="2026-10-01",
        )


def test_a_recorded_delay_is_not_scored(regional_databases):
    ksa = _snapshot("ksa", regional_databases["ksa"])
    by_id = {estimate.shipment_id: estimate for estimate in ksa.estimates}
    delayed = by_id["KSA-SHP-003"]
    delivered = by_id["KSA-SHP-001"]
    planned = by_id["KSA-SHP-004"]
    in_transit = by_id["KSA-SHP-002"]
    assert delayed.scored is False
    assert delayed.probability is None
    assert "already recorded as delayed" in delayed.reason
    assert delivered.scored is False
    assert "already recorded as delivered" in delivered.reason
    assert planned.scored is False
    assert "Departure date is not recorded" in planned.reason
    assert in_transit.scored is True
    assert in_transit.probability is not None
    assert 0.0 <= in_transit.probability <= 1.0
    assert len(in_transit.contributions) == 3

    pakistan = _snapshot("pakistan", regional_databases["pakistan"])
    assert pakistan.trained is True
    assert all(estimate.scored is False for estimate in pakistan.estimates)
    assert "No operational shipment is eligible" in pakistan.operational_note


def test_explanation_wording_stays_descriptive(regional_databases):
    snapshot = _snapshot("ksa", regional_databases["ksa"])
    scored = next(estimate for estimate in snapshot.estimates if estimate.scored)
    text = "\n".join(
        [
            snapshot.disclaimer,
            snapshot.target,
            scored.sentence,
            *(item.sentence for item in scored.contributions),
        ]
    )
    _assert_clean_wording(text)
    assert "synthetic ml demonstration" in snapshot.disclaimer.lower()
    assert "estimate based on synthetic historical data" in snapshot.disclaimer.lower()
    assert "not a real-world forecast" in snapshot.disclaimer.lower()
    assert scored.sentence.startswith("The model estimates a ")
    assert "not a real-world forecast" in scored.sentence
    directions = " ".join(item.sentence for item in scored.contributions)
    assert (
        "increased the model estimate" in directions
        or "decreased the model estimate" in directions
        or "did not change the model estimate" in directions
    )
    sample = explain_contributions(
        coefficients=[0.2, -0.1, 0.0, 0.4, -0.3],
        scaled_values=[1.0, 1.0, 1.0, 1.0, 1.0],
        raw_values={name: 1.0 for name in FEATURE_COLUMNS},
    )
    assert [item.feature for item in sample] == [
        "supplier_prior_late_rate",
        "supplier_prior_trip_count",
        "supplier_lead_time_days",
    ]
    _assert_clean_wording(probability_sentence(0.72))
    _assert_clean_wording("\n".join(item.sentence for item in sample))


def test_history_does_not_change_mvp2_metrics_risks_or_audits(regional_databases):
    for region_code, path, risk_ids, metrics in (
        (
            "ksa",
            regional_databases["ksa"],
            KSA_RISK_IDS,
            {
                "suppliers": 4,
                "products": 6,
                "open_purchase_orders": 3,
                "shipments_in_transit": 1,
                "delayed_shipments": 1,
                "low_stock_lines": 2,
            },
        ),
        (
            "pakistan",
            regional_databases["pakistan"],
            PAKISTAN_RISK_IDS,
            {
                "suppliers": 4,
                "products": 6,
                "open_purchase_orders": 2,
                "shipments_in_transit": 0,
                "delayed_shipments": 2,
                "low_stock_lines": 3,
            },
        ),
    ):
        repository = RegionRepository(region_code, database_path=path)
        scope = repository.load_scope()
        chain_id = scope.supply_chain.id
        audits_before = repository.list_audit_events()
        reviews_before = repository.list_reviews()
        risks, indicators = repository.load_risks(now="2026-10-08T00:00:00+00:00")
        metric_map = {
            metric.key: metric.value
            for metric in build_metrics(
                repository.list_suppliers(chain_id),
                repository.list_products(chain_id),
                repository.list_purchase_orders(chain_id),
                repository.list_shipments(chain_id),
                repository.list_inventory(chain_id),
            )
        }
        indicator_before = _indicator_signature(indicators)
        _snapshot(region_code, path)
        risks_after, indicators_after = repository.load_risks(now="2026-10-08T00:00:00+00:00")
        assert {risk.id for risk in risks} == risk_ids
        assert {risk.id for risk in risks_after} == risk_ids
        assert [risk.status for risk in risks] == [risk.status for risk in risks_after]
        assert metric_map == metrics
        assert _indicator_signature(indicators_after) == indicator_before
        assert all("Insufficient evidence" in item.delay_proportion_text for item in indicators)
        assert repository.list_reviews() == reviews_before
        assert [event.id for event in repository.list_audit_events()] == [
            event.id for event in audits_before
        ]
        assert len(repository.list_shipments(chain_id)) == 4
        assert len(repository.list_shipment_history(chain_id)) == 48
        connection = sqlite3.connect(path)
        try:
            shipment_count = connection.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
            history_count = connection.execute(
                "SELECT COUNT(*) FROM shipment_history"
            ).fetchone()[0]
            meta = dict(connection.execute("SELECT key, value FROM app_meta"))
        finally:
            connection.close()
        assert shipment_count == 4
        assert history_count == 48
        assert meta["shipment_history_role"] == "synthetic_ml_demonstration"
        assert meta["dataset_as_of"] == "2026-10-01"


def test_seeded_scoring_rows_and_class_counts(regional_databases):
    for region_code in ("ksa", "pakistan"):
        snapshot = _snapshot(region_code, regional_databases[region_code])
        assert snapshot.history_rows == 48
        assert snapshot.excluded_rows == 12
        assert snapshot.trainable_rows == 36
        assert snapshot.late_count == 17
        assert snapshot.on_time_count == 19
        assert snapshot.dataset_as_of == "2026-10-01"
        assert "synthetic_ml_demonstration" not in snapshot.disclaimer
        assert "Synthetic ML demonstration" in snapshot.disclaimer


def test_history_validation_rejects_a_short_file_and_a_future_date():
    with pytest.raises(ValueError, match="48"):
        _validate_shipment_history(pd.DataFrame([_history_record(1)]), set())
    rows = [_history_record(index) for index in range(1, 49)]
    rows[-1]["arrived_on"] = "2026-10-02"
    with pytest.raises(ValueError, match="as-of"):
        _validate_shipment_history(pd.DataFrame(rows), set())
    overlap = [_history_record(index) for index in range(1, 49)]
    overlap[0]["id"] = "KSA-SHP-001"
    with pytest.raises(ValueError, match="operational shipment"):
        _validate_shipment_history(pd.DataFrame(overlap), {"KSA-SHP-001"})


def test_summary_says_when_accuracy_is_below_the_majority_baseline():
    weaker = _evaluation_report(accuracy=0.44, majority_accuracy=0.56)
    assert "below the majority-class baseline" in weaker.summary()
    stronger = _evaluation_report(accuracy=0.70, majority_accuracy=0.56)
    assert "below the majority-class baseline" not in stronger.summary()


def test_ksa_chronological_holdout_is_below_the_majority_baseline(regional_databases):
    snapshot = _snapshot("ksa", regional_databases["ksa"])
    assert snapshot.chronological.accuracy < snapshot.chronological.majority_accuracy
    assert "below the majority-class baseline" in snapshot.chronological.summary()


def test_prediction_package_does_not_persist_a_model_or_call_an_llm():
    package = Path(__file__).resolve().parents[1] / "prediction"
    text = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py")).lower()
    assert "joblib" not in text
    assert "pickle" not in text
    assert "langgraph" not in text
    assert "langchain" not in text
    assert "import llm" not in text
    assert ".dump(" not in text


def _evaluation_report(accuracy: float, majority_accuracy: float) -> EvaluationReport:
    return EvaluationReport(
        name="chronological",
        role="primary",
        available=True,
        refusal_reason="",
        train_rows=27,
        test_rows=9,
        train_late=13,
        train_on_time=14,
        test_late=4,
        test_on_time=5,
        accuracy=accuracy,
        balanced_accuracy=0.42,
        late_precision=0.33,
        late_recall=0.25,
        roc_auc=0.40,
        majority_accuracy=majority_accuracy,
        majority_balanced_accuracy=0.50,
    )


def _assert_metric_bounds(report) -> None:
    for value in (
        report.accuracy,
        report.balanced_accuracy,
        report.late_precision,
        report.late_recall,
        report.roc_auc,
        report.majority_accuracy,
        report.majority_balanced_accuracy,
    ):
        assert value is not None
        assert 0.0 <= value <= 1.0


def _assert_clean_wording(text: str) -> None:
    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        assert phrase not in lowered


def _snapshot(region_code: str, database_path: Path):
    repository = RegionRepository(region_code, database_path=database_path)
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    return build_prediction_snapshot(
        history=repository.list_shipment_history(chain_id),
        suppliers=repository.list_suppliers(chain_id),
        shipments=repository.list_shipments(chain_id),
        orders=repository.list_purchase_orders(chain_id),
        dataset_as_of=repository.dataset_as_of(),
    )


def _history_and_lead(region_code: str, database_path: Path):
    repository = RegionRepository(region_code, database_path=database_path)
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    lead = {
        supplier.id: supplier.lead_time_days
        for supplier in repository.list_suppliers(chain_id)
    }
    return repository.list_shipment_history(chain_id), lead


def _indicator_signature(indicators) -> list[tuple[str, int, int, str]]:
    return [
        (
            item.supplier_id,
            item.delayed_shipment_count,
            item.linked_shipment_count,
            item.order_share_text,
        )
        for item in indicators
    ]


def _trip(trip_id, supplier_id, departed, eta, arrived) -> ShipmentHistoryTrip:
    return ShipmentHistoryTrip(
        id=trip_id,
        supply_chain_id="KSA-SC-001",
        supplier_id=supplier_id,
        origin="Riyadh",
        destination="Jeddah",
        departed_on=departed.isoformat(),
        eta=eta.isoformat(),
        arrived_on=arrived.isoformat(),
    )


def _flip_arrival(trip: ShipmentHistoryTrip) -> ShipmentHistoryTrip:
    eta = date.fromisoformat(trip.eta)
    arrived = date.fromisoformat(trip.arrived_on)
    updated = eta if arrived > eta else eta + timedelta(days=2)
    return trip.model_copy(update={"arrived_on": updated.isoformat()})


def _series(supplier_id: str, count: int, late_until: int) -> list[ShipmentHistoryTrip]:
    trips = []
    for index in range(count):
        departed = date(2026, 4, 1) + timedelta(days=index)
        eta = departed + timedelta(days=4)
        late = index < late_until
        arrived = eta + timedelta(days=2 if late else 0)
        trips.append(
            _trip(f"KSA-HST-{index:03d}", supplier_id, departed, eta, arrived)
        )
    return trips


def _feature_row(
    trip_id: str,
    *,
    late: int,
    departed: date | None = None,
    lead: float = 5.0,
    transit: float = 6.0,
    same: float = 0.0,
    rate: float = 0.25,
    prior: float = 4.0,
):
    from prediction.features import FeatureRow

    return FeatureRow(
        trip_id=trip_id,
        supplier_id="KSA-SUP-001",
        departed_on=(departed or date(2026, 5, 1)).isoformat(),
        late=late,
        values={
            "supplier_lead_time_days": lead,
            "planned_transit_days": transit,
            "same_city": same,
            "supplier_prior_late_rate": rate,
            "supplier_prior_trip_count": prior,
        },
        included=True,
        exclusion_reason="",
    )


def _supplier() -> Supplier:
    return Supplier(
        id="KSA-SUP-001",
        supply_chain_id="KSA-SC-001",
        name="Oasis Gate Demo Foods",
        city="Riyadh",
        status=SupplierStatus.ACTIVE,
        lead_time_days=5,
    )


def _order() -> PurchaseOrder:
    return PurchaseOrder(
        id="KSA-PO-001",
        supply_chain_id="KSA-SC-001",
        supplier_id="KSA-SUP-001",
        warehouse_id="KSA-WH-001",
        status=OrderStatus.OPEN,
        ordered_on="2026-01-01",
        expected_on="2026-02-01",
    )


def _operational(shipment_id: str, status: ShipmentStatus, departed: str, eta: str) -> Shipment:
    return Shipment(
        id=shipment_id,
        purchase_order_id="KSA-PO-001",
        origin="Riyadh",
        destination="Jeddah",
        status=status,
        departed_on=departed,
        eta=eta,
        arrived_on=None,
    )


def _history_record(index: int) -> dict[str, str]:
    departed = date(2026, 4, 1) + timedelta(days=index)
    eta = departed + timedelta(days=3)
    return {
        "id": f"KSA-HST-{index:03d}",
        "supply_chain_id": "KSA-SC-001",
        "supplier_id": "KSA-SUP-001",
        "origin": "Riyadh",
        "destination": "Jeddah",
        "departed_on": departed.isoformat(),
        "eta": eta.isoformat(),
        "arrived_on": eta.isoformat(),
    }
