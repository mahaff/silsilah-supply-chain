"""Draft a report, then accept or dismiss it. One pass. No retries."""

import hashlib
import json

from investigation.report import (
    ClaimRejected,
    InvestigationError,
    InvestigationReport,
    StaleInvestigation,
    assemble_report,
)
from investigation.subjects import assert_subject
from investigation.tools import gather, investigation_fingerprint
from persistence.repository import RegionRepository

STALE_MESSAGE = (
    "This investigation is stale. The underlying evidence changed, "
    "so it cannot be accepted or dismissed."
)


def run_investigation(
    repository: RegionRepository,
    kind: str,
    subject_id: str,
    *,
    now: str,
) -> InvestigationReport:
    """Gather evidence once and store a draft. Writing the draft is not a decision."""
    assert_subject(repository.config.region_code, kind, subject_id)
    gathered = gather(repository, kind, subject_id)
    fingerprint = investigation_fingerprint(kind, subject_id, gathered)
    investigation_id = _investigation_id(repository.config.region_code, kind, fingerprint)
    try:
        report = assemble_report(
            investigation_id=investigation_id,
            region_code=repository.config.region_code,
            subject_kind=kind,
            subject_id=subject_id,
            evidence_fingerprint=fingerprint,
            fields=gathered.fields,
            subject_rule_id=gathered.subject_rule_id,
            now=now,
        )
    except ClaimRejected as exc:
        raise InvestigationError(str(exc)) from exc
    before = len(repository.list_audit_events())
    stored = repository.save_investigation_draft(
        investigation_id=report.id,
        subject_kind=report.subject_kind,
        subject_id=report.subject_id,
        evidence_fingerprint=report.evidence_fingerprint,
        report_json=report.model_dump_json(),
        now=now,
    )
    after = len(repository.list_audit_events())
    if after != before:
        raise InvestigationError("Drafting created an audit event.")
    return _report_from_row(stored)


def accept_investigation(
    repository: RegionRepository,
    investigation_id: str,
    *,
    now: str,
) -> InvestigationReport:
    """Acknowledge the report. This does not review or resolve a risk."""
    return _decide(repository, investigation_id, "accepted", now=now)


def dismiss_investigation(
    repository: RegionRepository,
    investigation_id: str,
    *,
    now: str,
) -> InvestigationReport:
    """Record that a person set the report aside. Operational rows stay as they are."""
    return _decide(repository, investigation_id, "dismissed", now=now)


def _decide(
    repository: RegionRepository,
    investigation_id: str,
    decision: str,
    *,
    now: str,
) -> InvestigationReport:
    stored = repository.get_investigation(investigation_id)
    if stored is None:
        raise InvestigationError("That investigation is not in this region's database.")
    if stored["status"] == "stale":
        raise StaleInvestigation(STALE_MESSAGE)
    if stored["status"] != "draft":
        raise InvestigationError("This investigation is already decided.")
    report = _report_from_row(stored)
    assert_subject(repository.config.region_code, report.subject_kind, report.subject_id)
    fresh = gather(repository, report.subject_kind, report.subject_id)
    fingerprint = investigation_fingerprint(report.subject_kind, report.subject_id, fresh)
    if fingerprint != stored["evidence_fingerprint"]:
        repository.mark_investigation_stale(investigation_id, now=now)
        raise StaleInvestigation(STALE_MESSAGE)
    risk_id, rule_id = _audit_links(report)
    verb = "Accepted" if decision == "accepted" else "Dismissed"
    kinds = ", ".join(sorted({claim.evidence_kind for claim in report.claims}))
    summary = (
        f"{verb} investigation {report.id} for {report.subject_kind} {report.subject_id}. "
        "The finding is an investigation summary. "
        f"Cited evidence kinds: {kinds}. "
        "No operational record was changed."
    )
    before = len(repository.list_audit_events())
    try:
        repository.decide_investigation(
            investigation_id=investigation_id,
            decision=decision,
            evidence_fingerprint=fingerprint,
            now=now,
            summary=summary,
            risk_id=risk_id,
            rule_id=rule_id,
        )
    except ValueError as exc:
        raise InvestigationError(str(exc)) from exc
    after = repository.list_audit_events()
    if len(after) != before + 1:
        raise InvestigationError("A decision must write exactly one audit event.")
    if after[-1].action != f"investigation_{decision}":
        raise InvestigationError("The audit event does not match the decision.")
    updated = repository.get_investigation(investigation_id)
    if updated is None:
        raise InvestigationError("The decision was not stored.")
    return _report_from_row(updated)


def _audit_links(report: InvestigationReport) -> tuple[str | None, str | None]:
    if report.subject_kind != "risk":
        return None, None
    rule_id = next(
        (claim.value for claim in report.claims if claim.source == "risk" and claim.field == "rule_id"),
        None,
    )
    if rule_id is None:
        raise InvestigationError("A risk investigation has no rule id.")
    return report.subject_id, rule_id


def _investigation_id(region_code: str, kind: str, fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"inv:{region_code}:{kind}:{digest}"


def _report_from_row(row: dict[str, str]) -> InvestigationReport:
    payload = json.loads(row["report_json"])
    payload["status"] = row["status"]
    payload["evidence_fingerprint"] = row["evidence_fingerprint"]
    return InvestigationReport.model_validate(payload)
