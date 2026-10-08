"""Train and score the synthetic late-arrival demonstration.

The scoring model is fit in memory on this region's eligible history.
Evaluation numbers come from a chronological holdout and, separately,
a stratified random split. Nothing is written to disk.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from domain.models import (
    PurchaseOrder,
    Shipment,
    ShipmentHistoryTrip,
    ShipmentStatus,
    Supplier,
)
from prediction.explain import Contribution, explain_contributions, probability_sentence
from prediction.features import (
    FEATURE_COLUMNS,
    MIN_PRIOR_TRIPS,
    FeatureRow,
    build_feature_table,
    feature_matrix,
    features_for_departure,
)

RANDOM_STATE = 42
TEST_SIZE = 0.25
MIN_TRAINABLE_ROWS = 24
MIN_CLASS_COUNT = 6
MIN_HOLDOUT_PER_CLASS = 2

DISCLAIMER = (
    "Synthetic ML demonstration. This is an estimate based on synthetic historical data. "
    "It is not a real-world forecast, not a recorded fact, and not a compliance or legal determination. "
    "It does not change purchase orders, contact suppliers, or replace the risk register."
)

TARGET = (
    "Whether a departed shipment arrives after its expected date. "
    "Arrival on the expected date counts as not late."
)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    available: bool
    refusal_reason: str
    train_rows: int = 0
    test_rows: int = 0
    train_late: int = 0
    train_on_time: int = 0
    test_late: int = 0
    test_on_time: int = 0
    accuracy: float | None = None
    balanced_accuracy: float | None = None
    late_precision: float | None = None
    late_recall: float | None = None
    roc_auc: float | None = None
    majority_accuracy: float | None = None
    majority_balanced_accuracy: float | None = None
    train_ids: list[str] = Field(default_factory=list)
    test_ids: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        if not self.available:
            return self.refusal_reason
        auc = "not calculated" if self.roc_auc is None else f"{self.roc_auc:.2f}"
        comparison = ""
        if (
            self.accuracy is not None
            and self.majority_accuracy is not None
            and self.accuracy < self.majority_accuracy
        ):
            comparison = (
                " On this holdout, the demonstration model accuracy is below "
                "the majority-class baseline."
            )
        return (
            f"Training rows: {self.train_rows} "
            f"({self.train_late} late, {self.train_on_time} on time). "
            f"Test rows: {self.test_rows} "
            f"({self.test_late} late, {self.test_on_time} on time). "
            f"Accuracy: {self.accuracy:.2f}. "
            f"Balanced accuracy: {self.balanced_accuracy:.2f}. "
            f"Late precision: {self.late_precision:.2f}. "
            f"Late recall: {self.late_recall:.2f}. "
            f"ROC AUC: {auc}. "
            f"Majority-class baseline accuracy: {self.majority_accuracy:.2f}. "
            f"Majority-class baseline balanced accuracy: "
            f"{self.majority_balanced_accuracy:.2f}."
            f"{comparison}"
        )


class ShipmentEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str
    scored: bool
    probability: float | None
    sentence: str
    reason: str
    contributions: list[Contribution]


class PredictionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disclaimer: str
    target: str
    dataset_as_of: str
    history_rows: int
    excluded_rows: int
    trainable_rows: int
    late_count: int
    on_time_count: int
    trained: bool
    refusal_reason: str
    coefficients: list[float]
    chronological: EvaluationReport
    random_split: EvaluationReport
    operational_note: str
    estimates: list[ShipmentEstimate]

    def counts_summary(self) -> str:
        return (
            f"Synthetic history rows: {self.history_rows}. "
            f"Excluded from the model: {self.excluded_rows} "
            f"(fewer than {MIN_PRIOR_TRIPS} earlier trips for that supplier). "
            f"Rows used to fit the scoring model: {self.trainable_rows} "
            f"({self.late_count} late, {self.on_time_count} on time)."
        )


def make_estimator(*, balanced: bool = True) -> Pipeline:
    """Logistic regression on scaled features. The same seed is always used."""
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    class_weight="balanced" if balanced else None,
                    random_state=RANDOM_STATE,
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def trainable_rows(rows: list[FeatureRow]) -> list[FeatureRow]:
    included = [row for row in rows if row.included]
    return sorted(included, key=lambda row: (row.departed_on, row.trip_id))


def class_counts(rows: list[FeatureRow]) -> tuple[int, int]:
    late = sum(row.late for row in rows)
    return late, len(rows) - late


def training_block_reason(rows: list[FeatureRow]) -> str:
    late, on_time = class_counts(rows)
    if len(rows) < MIN_TRAINABLE_ROWS or late < MIN_CLASS_COUNT or on_time < MIN_CLASS_COUNT:
        return (
            "The synthetic history does not have enough labeled outcomes to train "
            "the demonstration model. "
            f"After excluding trips with fewer than {MIN_PRIOR_TRIPS} earlier trips, "
            f"{len(rows)} rows remain ({late} late, {on_time} on time). "
            f"Training needs at least {MIN_TRAINABLE_ROWS} rows and at least "
            f"{MIN_CLASS_COUNT} of each outcome. No probability is shown."
        )
    return ""


def fit_scoring_model(rows: list[FeatureRow], *, balanced: bool = True) -> Pipeline | None:
    """Fit on every eligible row. Returns None when the history is too small."""
    chosen = trainable_rows(rows)
    if training_block_reason(chosen):
        return None
    pipeline = make_estimator(balanced=balanced)
    pipeline.fit(feature_matrix(chosen), [row.late for row in chosen])
    return pipeline


def chronological_holdout(rows: list[FeatureRow]) -> tuple[list[FeatureRow], list[FeatureRow], str]:
    """Earlier trips train. Later trips test. Refuse a one-sided holdout."""
    ordered = trainable_rows(rows)
    if training_block_reason(ordered):
        return [], [], (
            "The chronological holdout is not reported because the scoring model "
            "was not trained."
        )
    test_count = len(ordered) // 4
    if test_count < MIN_HOLDOUT_PER_CLASS * 2:
        return [], [], (
            "The chronological holdout is not reported. "
            "There are not enough labeled trips to hold out a later block with both outcomes."
        )
    test = ordered[-test_count:]
    train = ordered[:-test_count]
    if train and test and max(row.departed_on for row in train) > min(row.departed_on for row in test):
        return [], [], (
            "The chronological holdout is not reported. "
            "A later test trip would have departed before a training trip."
        )
    test_late, test_on_time = class_counts(test)
    train_late, train_on_time = class_counts(train)
    if test_late < MIN_HOLDOUT_PER_CLASS or test_on_time < MIN_HOLDOUT_PER_CLASS:
        return [], [], (
            "The chronological holdout is not reported. "
            "The later trips do not include at least two late outcomes and two on-time outcomes, "
            "so a time-ordered test would not be meaningful."
        )
    if train_late < 1 or train_on_time < 1:
        return [], [], (
            "The chronological holdout is not reported. "
            "The earlier trips contain only one outcome, so the time-ordered model "
            "would not be meaningful."
        )
    return train, test, ""


def random_holdout(rows: list[FeatureRow]) -> tuple[list[FeatureRow], list[FeatureRow], str]:
    """Stratified shuffle. This is a reproducibility check, not a time order."""
    ordered = trainable_rows(rows)
    if training_block_reason(ordered):
        return [], [], (
            "The stratified random split is not reported because the scoring model "
            "was not trained."
        )
    labels = [row.late for row in ordered]
    if labels.count(0) < 2 or labels.count(1) < 2:
        return [], [], (
            "The stratified random split is not reported. "
            "The labeled trips do not support a 25 percent stratified holdout "
            f"with random_state {RANDOM_STATE}."
        )
    try:
        train, test = train_test_split(
            ordered,
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
            stratify=labels,
        )
    except ValueError:
        return [], [], (
            "The stratified random split is not reported. "
            "The labeled trips do not support a 25 percent stratified holdout "
            f"with random_state {RANDOM_STATE}."
        )
    return list(train), list(test), ""


def evaluate_split(
    name: str,
    role: str,
    train: list[FeatureRow],
    test: list[FeatureRow],
    refusal_reason: str,
) -> EvaluationReport:
    if refusal_reason or not train or not test:
        return EvaluationReport(
            name=name,
            role=role,
            available=False,
            refusal_reason=refusal_reason
            or "This evaluation is not reported because a train or test block is empty.",
        )
    pipeline = make_estimator(balanced=True)
    pipeline.fit(feature_matrix(train), [row.late for row in train])
    test_matrix = feature_matrix(test)
    y_true = [row.late for row in test]
    y_pred = [int(value) for value in pipeline.predict(test_matrix)]
    y_score = _late_probabilities(pipeline, test_matrix)
    train_late, train_on_time = class_counts(train)
    test_late, test_on_time = class_counts(test)
    majority = 1 if train_late >= train_on_time else 0
    majority_pred = [majority] * len(y_true)
    roc_auc = None
    if test_late > 0 and test_on_time > 0:
        roc_auc = float(roc_auc_score(y_true, y_score))
    return EvaluationReport(
        name=name,
        role=role,
        available=True,
        refusal_reason="",
        train_rows=len(train),
        test_rows=len(test),
        train_late=train_late,
        train_on_time=train_on_time,
        test_late=test_late,
        test_on_time=test_on_time,
        accuracy=float(accuracy_score(y_true, y_pred)),
        balanced_accuracy=float(balanced_accuracy_score(y_true, y_pred)),
        late_precision=float(precision_score(y_true, y_pred, pos_label=1, zero_division=0)),
        late_recall=float(recall_score(y_true, y_pred, pos_label=1, zero_division=0)),
        roc_auc=roc_auc,
        majority_accuracy=float(accuracy_score(y_true, majority_pred)),
        majority_balanced_accuracy=float(balanced_accuracy_score(y_true, majority_pred)),
        train_ids=[row.trip_id for row in train],
        test_ids=[row.trip_id for row in test],
    )


def build_prediction_snapshot(
    *,
    history: list[ShipmentHistoryTrip],
    suppliers: list[Supplier],
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
    dataset_as_of: str,
) -> PredictionSnapshot:
    """Train from this history only and score eligible operational shipments."""
    _refuse_mixed_regions(history, shipments)
    lead_times = {supplier.id: supplier.lead_time_days for supplier in suppliers}
    feature_rows = build_feature_table(history, lead_times)
    chosen = trainable_rows(feature_rows)
    late_count, on_time_count = class_counts(chosen)
    refusal = training_block_reason(chosen)
    pipeline = None if refusal else fit_scoring_model(feature_rows, balanced=True)
    coefficients = []
    if pipeline is not None:
        coefficients = [float(value) for value in pipeline.named_steps["model"].coef_[0]]

    chronological = _chronological_report(history, lead_times, feature_rows)
    random_train, random_test, random_reason = random_holdout(feature_rows)
    random_split = evaluate_split(
        "random",
        "secondary",
        random_train,
        random_test,
        random_reason,
    )
    estimates = _score_shipments(
        history=history,
        lead_times=lead_times,
        shipments=shipments,
        orders=orders,
        pipeline=pipeline,
        refusal=refusal,
    )
    scored_any = any(estimate.scored for estimate in estimates)
    if refusal:
        operational_note = refusal
    elif scored_any:
        operational_note = (
            "Estimates below are only for in-transit shipments that already have "
            "a departure date. A recorded delay or delivery is not scored."
        )
    else:
        operational_note = (
            "No operational shipment is eligible for an estimate in this region. "
            "Nothing below is a prediction."
        )
    return PredictionSnapshot(
        disclaimer=DISCLAIMER,
        target=TARGET,
        dataset_as_of=dataset_as_of,
        history_rows=len(history),
        excluded_rows=len(feature_rows) - len(chosen),
        trainable_rows=len(chosen),
        late_count=late_count,
        on_time_count=on_time_count,
        trained=pipeline is not None,
        refusal_reason=refusal,
        coefficients=coefficients,
        chronological=chronological,
        random_split=random_split,
        operational_note=operational_note,
        estimates=estimates,
    )


def _chronological_report(
    history: list[ShipmentHistoryTrip],
    lead_times: dict[str, int],
    feature_rows: list[FeatureRow],
) -> EvaluationReport:
    train, test, reason = chronological_holdout(feature_rows)
    if reason:
        return evaluate_split("chronological", "primary", train, test, reason)
    if not _training_features_ignore_later_trips(history, lead_times, train, test):
        return evaluate_split(
            "chronological",
            "primary",
            [],
            [],
            (
                "The chronological holdout is not reported. "
                "Training features changed when later trips were removed, "
                "so the split would not be independent of future trips."
            ),
        )
    return evaluate_split("chronological", "primary", train, test, "")


def _training_features_ignore_later_trips(
    history: list[ShipmentHistoryTrip],
    lead_times: dict[str, int],
    train: list[FeatureRow],
    test: list[FeatureRow],
) -> bool:
    """Recompute training rows without the later test trips.

    If a coefficient input changes, the holdout was not independent of the future.
    """
    test_ids = {row.trip_id for row in test}
    reduced_history = [trip for trip in history if trip.id not in test_ids]
    reduced = {
        row.trip_id: row
        for row in build_feature_table(reduced_history, lead_times)
    }
    for row in train:
        other = reduced.get(row.trip_id)
        if other is None or other.values != row.values or other.late != row.late:
            return False
    return True


def _score_shipments(
    *,
    history: list[ShipmentHistoryTrip],
    lead_times: dict[str, int],
    shipments: list[Shipment],
    orders: list[PurchaseOrder],
    pipeline: Pipeline | None,
    refusal: str,
) -> list[ShipmentEstimate]:
    supplier_by_order = {order.id: order.supplier_id for order in orders}
    estimates: list[ShipmentEstimate] = []
    for shipment in shipments:
        blocked = _known_outcome_reason(shipment)
        if blocked:
            estimates.append(_unscored(shipment.id, blocked))
            continue
        if pipeline is None:
            estimates.append(_unscored(shipment.id, refusal))
            continue
        supplier_id = supplier_by_order.get(shipment.purchase_order_id)
        if supplier_id is None or shipment.departed_on is None:
            estimates.append(
                _unscored(
                    shipment.id,
                    "Not scored. Departure date is not recorded, so the planned "
                    "transit length is unknown.",
                )
            )
            continue
        values, feature_reason = features_for_departure(
            history=history,
            lead_times=lead_times,
            shipment_id=shipment.id,
            supplier_id=supplier_id,
            origin=shipment.origin,
            destination=shipment.destination,
            departed_on=_date_from_iso(shipment.departed_on),
            eta=_date_from_iso(shipment.eta),
        )
        if values is None:
            estimates.append(_unscored(shipment.id, feature_reason))
            continue
        probability = _late_probabilities(pipeline, [list(values[name] for name in FEATURE_COLUMNS)])[0]
        scaled = pipeline.named_steps["scale"].transform(
            [[values[name] for name in FEATURE_COLUMNS]]
        )[0]
        coefficients = [float(value) for value in pipeline.named_steps["model"].coef_[0]]
        contributions = explain_contributions(
            coefficients=coefficients,
            scaled_values=[float(value) for value in scaled],
            raw_values=values,
        )
        estimates.append(
            ShipmentEstimate(
                shipment_id=shipment.id,
                scored=True,
                probability=probability,
                sentence=probability_sentence(probability),
                reason="",
                contributions=contributions,
            )
        )
    return estimates


def _known_outcome_reason(shipment: Shipment) -> str | None:
    status = shipment.status.value if isinstance(shipment.status, ShipmentStatus) else str(shipment.status)
    if status == ShipmentStatus.DELAYED.value:
        return (
            "Not scored. This shipment is already recorded as delayed, so the outcome is known. "
            "The risk register covers that recorded condition with a deterministic rule."
        )
    if status == ShipmentStatus.DELIVERED.value:
        return (
            "Not scored. This shipment is already recorded as delivered, so the outcome is known."
        )
    if status == ShipmentStatus.PLANNED.value or not shipment.departed_on:
        return (
            "Not scored. Departure date is not recorded, so the planned transit length is unknown."
        )
    if status != ShipmentStatus.IN_TRANSIT.value:
        return (
            "Not scored. Only an in-transit shipment with a departure date can receive an estimate."
        )
    return None


def _unscored(shipment_id: str, reason: str) -> ShipmentEstimate:
    return ShipmentEstimate(
        shipment_id=shipment_id,
        scored=False,
        probability=None,
        sentence="",
        reason=reason,
        contributions=[],
    )


def _late_probabilities(pipeline: Pipeline, matrix: list[list[float]]) -> list[float]:
    probabilities = pipeline.predict_proba(matrix)
    classes = [int(value) for value in pipeline.named_steps["model"].classes_]
    if 1 not in classes:
        raise ValueError("The demonstration model has no late-arrival outcome to score.")
    column = classes.index(1)
    return [float(row[column]) for row in probabilities]


def _refuse_mixed_regions(
    history: list[ShipmentHistoryTrip],
    shipments: list[Shipment],
) -> None:
    supplier_ids = [trip.supplier_id for trip in history]
    shipment_ids = [shipment.id for shipment in shipments]
    texts = supplier_ids + shipment_ids
    has_ksa = any(value.startswith("KSA-") for value in texts)
    has_pakistan = any(value.startswith("PAK-") for value in texts)
    if has_ksa and has_pakistan:
        raise ValueError(
            "Shipment history mixes Saudi Arabia and Pakistan suppliers. "
            "Refusing to train on both regions together."
        )


def _date_from_iso(value: str) -> date:
    return date.fromisoformat(value)
