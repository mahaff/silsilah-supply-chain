"""Claim templates and the checks that keep a report inside retrieved fields."""

import re

from pydantic import BaseModel, ConfigDict

TOKEN_RE = re.compile(
    r"(?:ksa|pakistan):[A-Za-z0-9_.-]+:[A-Za-z0-9-]+|[A-Z]{3}-[A-Z]+-\d+|\d+(?:\.\d+)?"
)

BANNED_PHRASES: tuple[str, ...] = (
    "caused",
    "will be late",
    "definitely",
    "confirms the",
    "guaranteed",
)

FINDING = (
    "This report restates the fields retrieved for this subject. "
    "It is an investigation summary."
)
FINDING_KIND = "investigation_summary"

BASE_NOTICES: tuple[str, ...] = (
    "Synthetic data. This report only restates retrieved fields.",
    "This is not a legal or compliance determination.",
    "Accepting this report does not mark a risk reviewed or resolved.",
)
ESTIMATE_NOTICE = "This is not a real-world forecast."
SEPARATION_NOTICE = (
    "The model estimate and the deterministic rule are separate. "
    "The estimate does not confirm the rule."
)
SUPPLIER_NOTICE = "The predictive model history is not evidence for this supplier rule."

NEXT_STEPS: tuple[str, ...] = (
    "A person can inspect the cited rows in this region.",
    "Any operational decision happens outside this application.",
    "Accepting this report does not mark a risk reviewed or resolved.",
)

GAP_TEXT: dict[str, str] = {
    "insufficient_demand_history": (
        "Demand history is insufficient for a coverage figure. No stockout date is estimated."
    ),
    "delay_proportion_withheld": (
        "The delay proportion is withheld because there are not enough linked shipments."
    ),
    "prediction_not_scored": (
        "No late-arrival probability is attached because this shipment is not scored."
    ),
    "estimate_alongside_known_condition": (
        "A deterministic rule and a model estimate both refer to this shipment. "
        "They are separate evidence."
    ),
    "model_below_baseline": (
        "The chronological holdout accuracy is below the majority-class baseline. "
        "This is not real-world forecasting performance."
    ),
}

TEMPLATES: dict[tuple[str, str], str] = {
    ("risk", "explanation"): "{value}",
    ("risk", "rule_id"): "Rule id is {value}.",
    ("app_meta", "dataset_as_of"): "Synthetic dataset as-of date is {value}.",
    ("inventory", "on_hand"): "On hand is {value}.",
    ("inventory", "reorder_point"): "Reorder point is {value}.",
    ("inventory", "product_name"): "Product name is {value}.",
    ("inventory", "warehouse_name"): "Warehouse name is {value}.",
    ("inventory", "coverage_text"): "{value}",
    ("shipment", "status"): "Stored shipment status is {value}.",
    ("shipment", "eta"): "Expected arrival date is {value}.",
    ("shipment", "departed_on"): "Departure date is {value}.",
    ("shipment", "id"): "Shipment id is {value}.",
    ("shipment", "purchase_order_id"): "Purchase order id is {value}.",
    ("supplier", "name"): "Supplier name is {value}.",
    ("supplier", "id"): "Supplier id is {value}.",
    ("indicator", "delayed_shipment_count"): "Delayed shipment count is {value}.",
    ("indicator", "linked_shipment_count"): "Linked shipment count is {value}.",
    ("indicator", "delay_proportion_text"): "{value}",
    ("indicator", "order_share_text"): "{value}",
    ("indicator", "note"): "{value}",
    ("prediction", "probability"): (
        "The model estimates a {value} probability of arriving after the expected date."
    ),
    ("prediction", "chronological_accuracy"): "Chronological holdout accuracy is {value}.",
    ("prediction", "majority_accuracy"): "Majority-class baseline accuracy is {value}.",
    ("prediction", "below_baseline"): (
        "Chronological accuracy is below the majority-class baseline: {value}."
    ),
    ("prediction", "chronological_summary"): "{value}",
    ("prediction", "scored"): "Predictive demonstration scored this shipment: {value}.",
    ("prediction", "contribution_sentence"): "{value}",
    ("related_rule", "rule_id"): "Another deterministic rule on a linked record is {value}.",
}

FIELD_KINDS: dict[tuple[str, str], str] = {
    ("risk", "explanation"): "deterministic_rule",
    ("risk", "rule_id"): "deterministic_rule",
    ("app_meta", "dataset_as_of"): "database_fact",
    ("inventory", "on_hand"): "database_fact",
    ("inventory", "reorder_point"): "database_fact",
    ("inventory", "product_name"): "database_fact",
    ("inventory", "warehouse_name"): "database_fact",
    ("inventory", "coverage_text"): "deterministic_rule",
    ("shipment", "status"): "database_fact",
    ("shipment", "eta"): "database_fact",
    ("shipment", "departed_on"): "database_fact",
    ("shipment", "id"): "database_fact",
    ("shipment", "purchase_order_id"): "database_fact",
    ("supplier", "name"): "database_fact",
    ("supplier", "id"): "database_fact",
    ("indicator", "delayed_shipment_count"): "deterministic_rule",
    ("indicator", "linked_shipment_count"): "deterministic_rule",
    ("indicator", "delay_proportion_text"): "deterministic_rule",
    ("indicator", "order_share_text"): "deterministic_rule",
    ("indicator", "note"): "deterministic_rule",
    ("prediction", "probability"): "ml_prediction",
    ("prediction", "chronological_accuracy"): "ml_prediction",
    ("prediction", "majority_accuracy"): "ml_prediction",
    ("prediction", "below_baseline"): "ml_prediction",
    ("prediction", "chronological_summary"): "ml_prediction",
    ("prediction", "scored"): "ml_prediction",
    ("prediction", "contribution_sentence"): "ml_prediction",
    ("related_rule", "rule_id"): "deterministic_rule",
}

_SOURCE_ORDER = {
    "risk": 0,
    "app_meta": 1,
    "inventory": 2,
    "shipment": 3,
    "supplier": 4,
    "indicator": 5,
    "related_rule": 6,
    "prediction": 7,
}
_PREDICTION_ORDER = {
    "scored": 0,
    "probability": 1,
    "chronological_accuracy": 2,
    "majority_accuracy": 3,
    "below_baseline": 4,
    "chronological_summary": 5,
    "contribution_sentence": 6,
}


class InvestigationError(ValueError):
    """The investigation stopped before writing a decision."""


class StaleInvestigation(InvestigationError):
    """The stored fingerprint no longer matches the live records."""


class ClaimRejected(InvestigationError):
    """A sentence is not tied to one retrieved field."""


class RetrievedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    record_id: str
    field: str
    value: str
    evidence_kind: str


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    text: str
    source: str
    record_id: str
    field: str
    value: str
    evidence_kind: str


class Gap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    text: str


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    region_code: str
    subject_kind: str
    subject_id: str
    status: str
    evidence_fingerprint: str
    finding: str
    finding_evidence_kind: str
    notices: list[str]
    claims: list[Claim]
    gaps: list[Gap]
    next_steps: list[str]
    created_at: str
    updated_at: str


def _bare_template(template: str) -> str:
    return template.replace("{value}", "").replace("{record_id}", "")


def render_claim(field: RetrievedField) -> str:
    """Fill the one template registered for this source and field."""
    template = TEMPLATES.get((field.source, field.field))
    if template is None:
        raise ClaimRejected(f"No template for {field.source}.{field.field}.")
    if any(character.isdigit() for character in _bare_template(template)):
        raise ClaimRejected("A claim template contains a static digit.")
    return template.format(value=field.value, record_id=field.record_id)


def _field_sort_key(field: RetrievedField) -> tuple[int, str, int, str]:
    return (
        _SOURCE_ORDER.get(field.source, 99),
        field.record_id,
        _PREDICTION_ORDER.get(field.field, 0) if field.source == "prediction" else 0,
        field.field,
    )


def claims_from_fields(fields: list[RetrievedField]) -> list[Claim]:
    """One claim per retrieved field, in a stable order."""
    ordered = sorted(fields, key=_field_sort_key)
    claims: list[Claim] = []
    for index, field in enumerate(ordered, start=1):
        claims.append(
            Claim(
                citation_id=f"c{index}",
                text=render_claim(field),
                source=field.source,
                record_id=field.record_id,
                field=field.field,
                value=field.value,
                evidence_kind=field.evidence_kind,
            )
        )
    return claims


def _reject_banned(text: str) -> None:
    for phrase in BANNED_PHRASES:
        if phrase in text:
            raise ClaimRejected(f"Claim text contains unsupported wording: {phrase}.")


def _reject_foreign_tokens(claim: Claim) -> None:
    allowed = f"{claim.value}\n{claim.record_id}"
    for token in TOKEN_RE.findall(claim.text):
        if token not in allowed:
            raise ClaimRejected(
                f"Token {token} is not in this claim's field value or record id."
            )


def validate_claims(claims: list[Claim], fields: list[RetrievedField]) -> None:
    """Each claim must restate exactly one retrieved field.

    A number or id on a different claim does not support this claim.
    """
    if len(claims) != len(fields):
        raise ClaimRejected("Claim count does not match retrieved fields.")
    index: dict[tuple[str, str, str], RetrievedField] = {}
    for field in fields:
        key = (field.source, field.record_id, field.field)
        if key in index:
            raise ClaimRejected("Duplicate retrieved field.")
        if (field.source, field.field) not in TEMPLATES:
            raise ClaimRejected(f"No template for {field.source}.{field.field}.")
        expected_kind = FIELD_KINDS[(field.source, field.field)]
        if field.evidence_kind != expected_kind:
            raise ClaimRejected("Retrieved evidence kind does not match the field.")
        index[key] = field
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (claim.source, claim.record_id, claim.field)
        field = index.get(key)
        if field is None:
            raise ClaimRejected("Claim does not match a retrieved field.")
        if key in seen:
            raise ClaimRejected("Duplicate claim for one field.")
        seen.add(key)
        if claim.value != field.value or claim.record_id != field.record_id:
            raise ClaimRejected("Claim value does not match the retrieved field.")
        if claim.evidence_kind != field.evidence_kind:
            raise ClaimRejected("Claim evidence kind does not match the retrieved field.")
        if claim.text != render_claim(field):
            raise ClaimRejected("Claim text is not the template for this field.")
        _reject_banned(claim.text)
        _reject_foreign_tokens(claim)
    if seen != set(index):
        raise ClaimRejected("A retrieved field has no claim.")


def _only(fields: list[RetrievedField], source: str, field_name: str) -> RetrievedField | None:
    matches = [
        item for item in fields if item.source == source and item.field == field_name
    ]
    if len(matches) > 1:
        raise InvestigationError(f"Expected one {source}.{field_name} field.")
    return matches[0] if matches else None


def derive_gaps(fields: list[RetrievedField]) -> list[Gap]:
    """Fixed gap sentences chosen from retrieved values."""
    gaps: list[Gap] = []
    coverage = _only(fields, "inventory", "coverage_text")
    if coverage is not None and coverage.value.startswith("Insufficient demand history"):
        gaps.append(_gap("insufficient_demand_history"))
    proportion = _only(fields, "indicator", "delay_proportion_text")
    if proportion is not None and "Insufficient evidence" in proportion.value:
        gaps.append(_gap("delay_proportion_withheld"))
    scored = _only(fields, "prediction", "scored")
    if scored is not None and scored.value == "no":
        gaps.append(_gap("prediction_not_scored"))
    probability = _only(fields, "prediction", "probability")
    has_related_rule = any(
        item.source == "related_rule" and item.field == "rule_id" for item in fields
    )
    if probability is not None and has_related_rule:
        gaps.append(_gap("estimate_alongside_known_condition"))
    below = _only(fields, "prediction", "below_baseline")
    if below is not None and below.value == "yes":
        gaps.append(_gap("model_below_baseline"))
    return gaps


def _gap(code: str) -> Gap:
    return Gap(code=code, text=GAP_TEXT[code])


def derive_notices(
    fields: list[RetrievedField],
    subject_rule_id: str | None,
) -> list[str]:
    """Fixed notices. These are not claims and they cite no extra numbers."""
    notices = list(BASE_NOTICES)
    has_probability = _only(fields, "prediction", "probability") is not None
    has_rule = _only(fields, "risk", "rule_id") is not None or any(
        item.source == "related_rule" and item.field == "rule_id" for item in fields
    )
    if has_probability:
        notices.append(ESTIMATE_NOTICE)
    if has_probability and has_rule:
        notices.append(SEPARATION_NOTICE)
    if subject_rule_id is not None and subject_rule_id.startswith("supplier."):
        notices.append(SUPPLIER_NOTICE)
    return notices


def assemble_report(
    *,
    investigation_id: str,
    region_code: str,
    subject_kind: str,
    subject_id: str,
    evidence_fingerprint: str,
    fields: list[RetrievedField],
    subject_rule_id: str | None,
    now: str,
) -> InvestigationReport:
    """Build a draft and reject it when any claim fails validation."""
    claims = claims_from_fields(fields)
    validate_claims(claims, fields)
    report = InvestigationReport(
        id=investigation_id,
        region_code=region_code,
        subject_kind=subject_kind,
        subject_id=subject_id,
        status="draft",
        evidence_fingerprint=evidence_fingerprint,
        finding=FINDING,
        finding_evidence_kind=FINDING_KIND,
        notices=derive_notices(fields, subject_rule_id),
        claims=claims,
        gaps=derive_gaps(fields),
        next_steps=list(NEXT_STEPS),
        created_at=now,
        updated_at=now,
    )
    validate_report_frame(report)
    return report


def validate_report_frame(report: InvestigationReport) -> None:
    """Notices, gaps, and next steps stay on the allow-list."""
    if report.finding != FINDING or report.finding_evidence_kind != FINDING_KIND:
        raise ClaimRejected("The finding is not the investigation summary.")
    if tuple(report.next_steps) != NEXT_STEPS:
        raise ClaimRejected("Next steps were changed.")
    for step in report.next_steps:
        if TOKEN_RE.findall(step):
            raise ClaimRejected("A next step contains an id or a number.")
    allowed_notices = {
        *BASE_NOTICES,
        ESTIMATE_NOTICE,
        SEPARATION_NOTICE,
        SUPPLIER_NOTICE,
    }
    if any(notice not in allowed_notices for notice in report.notices):
        raise ClaimRejected("A notice is not on the allow-list.")
    for gap in report.gaps:
        if GAP_TEXT.get(gap.code) != gap.text:
            raise ClaimRejected("A gap is not on the allow-list.")
    if report.status not in {"draft", "accepted", "dismissed", "stale"}:
        raise ClaimRejected("Unknown investigation status.")


def _registry_ok() -> None:
    if set(TEMPLATES) != set(FIELD_KINDS):
        raise RuntimeError("Claim templates and evidence kinds do not match.")
    for template in TEMPLATES.values():
        if any(character.isdigit() for character in _bare_template(template)):
            raise RuntimeError("A claim template contains a static digit.")


_registry_ok()
