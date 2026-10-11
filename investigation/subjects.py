"""Subject identity checks. A report may only cite the selected region."""

from investigation.report import InvestigationError

RISK_PREFIX = {"ksa": "ksa:", "pakistan": "pakistan:"}
RECORD_PREFIX = {"ksa": "KSA-", "pakistan": "PAK-"}
OTHER_MARKERS = {
    "ksa": ("pakistan:", "PAK-"),
    "pakistan": ("ksa:", "KSA-"),
}


def assert_subject(region_code: str, kind: str, subject_id: str) -> None:
    """Reject a subject that is not a risk or estimate in this region."""
    if kind not in {"risk", "estimate"}:
        raise InvestigationError("Subject kind must be risk or estimate.")
    if region_code not in RISK_PREFIX:
        raise InvestigationError("Unknown region.")
    if kind == "risk":
        if not subject_id.startswith(RISK_PREFIX[region_code]):
            raise InvestigationError("This risk id does not belong to the selected region.")
    elif not subject_id.startswith(RECORD_PREFIX[region_code]):
        raise InvestigationError("This shipment id does not belong to the selected region.")
    assert_regional_text(region_code, subject_id)


def assert_regional_text(region_code: str, text: str) -> None:
    """Abort when text carries an id from the other region."""
    if region_code not in OTHER_MARKERS:
        raise InvestigationError("Unknown region.")
    for marker in OTHER_MARKERS[region_code]:
        if marker in text:
            raise InvestigationError("Evidence from the other region was refused.")


def assert_fields_regional(region_code: str, fields: list) -> None:
    """Scan every retrieved id and value before a report is saved."""
    for field in fields:
        assert_regional_text(region_code, field.record_id)
        assert_regional_text(region_code, field.value)
        assert_regional_text(region_code, field.source)
        assert_regional_text(region_code, field.field)
