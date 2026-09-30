"""Build the governance status shown on the war-room screen.

This module does not contain laws, articles, or compliance claims.
It reports how many reference rows are stored. In MVP 1 that number is zero
because no official source has been entered.
"""

from pydantic import BaseModel, ConfigDict

from domain.models import AuditEvent

DISCLAIMER = (
    "Silsilah does not provide legal advice and does not certify compliance."
)

EMPTY_REFERENCES_NOTE = (
    "Regulatory reference records: none. "
    "Official government or regulator sources can be added later, with the "
    "source URL and the date they were checked. "
    "This panel does not state legal requirements."
)


class GovernanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_display_name: str
    data_classification: str
    references_loaded: int
    disclaimer: str
    references_note: str
    latest_audit_summary: str
    latest_audit_at: str


def build_governance_status(
    region_display_name: str,
    references_loaded: int,
    latest_audit: AuditEvent | None,
) -> GovernanceStatus:
    """Assemble the status panel from counts and the latest audit row."""
    if latest_audit is None:
        audit_summary = "No audit record is stored yet."
        audit_at = ""
    else:
        audit_summary = latest_audit.summary
        audit_at = latest_audit.occurred_at

    if references_loaded == 0:
        note = EMPTY_REFERENCES_NOTE
    else:
        # A later phase may load official rows. MVP 1 does not write any.
        note = f"{references_loaded} regulatory reference records are stored for this region."

    return GovernanceStatus(
        region_display_name=region_display_name,
        data_classification="Synthetic",
        references_loaded=references_loaded,
        disclaimer=DISCLAIMER,
        references_note=note,
        latest_audit_summary=audit_summary,
        latest_audit_at=audit_at,
    )
