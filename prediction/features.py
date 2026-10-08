"""Labels and features for the synthetic late-arrival demonstration.

A feature is something known when a trip departs. Arrival, lateness, and
shipment status are not features. Supplier history uses only trips that
departed strictly earlier.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from domain.models import ShipmentHistoryTrip

FEATURE_COLUMNS: tuple[str, ...] = (
    "supplier_lead_time_days",
    "planned_transit_days",
    "same_city",
    "supplier_prior_late_rate",
    "supplier_prior_trip_count",
)

# Names that would copy the outcome into the model. They are rejected.
FORBIDDEN_FEATURE_NAMES: frozenset[str] = frozenset(
    {
        "arrived_on",
        "arrival",
        "status",
        "late",
        "lateness",
        "label",
        "eta",
        "departed_on",
    }
)

MIN_PRIOR_TRIPS = 3


class FeatureRow(BaseModel):
    """One history trip after the allow-list is applied."""

    model_config = ConfigDict(extra="forbid")

    trip_id: str
    supplier_id: str
    departed_on: str
    late: int = Field(ge=0, le=1)
    values: dict[str, float]
    included: bool
    exclusion_reason: str


class ParsedTrip(BaseModel):
    """Dates parsed once so comparisons do not depend on row order."""

    model_config = ConfigDict(extra="forbid")

    id: str
    supplier_id: str
    origin: str
    destination: str
    departed: date
    eta: date
    arrived: date

    @property
    def late(self) -> int:
        return 1 if is_late(self.arrived, self.eta) else 0


def is_late(arrived_on: date, eta: date) -> bool:
    """Late means arrival is after the expected date.

    An arrival on the expected date is not late.
    """
    return arrived_on > eta


def build_feature_table(
    trips: list[ShipmentHistoryTrip],
    lead_times: dict[str, int],
) -> list[FeatureRow]:
    """Build one feature row per history trip.

    Rows with fewer than three earlier trips for the same supplier are
    marked excluded. Their outcomes can still inform later rows.
    """
    parsed = [_parse_trip(trip, lead_times) for trip in trips]
    rows: list[FeatureRow] = []
    for trip in parsed:
        prior = _earlier_trips(parsed, trip.supplier_id, trip.departed, ignore_id=trip.id)
        if len(prior) < MIN_PRIOR_TRIPS:
            rows.append(
                FeatureRow(
                    trip_id=trip.id,
                    supplier_id=trip.supplier_id,
                    departed_on=trip.departed.isoformat(),
                    late=trip.late,
                    values={},
                    included=False,
                    exclusion_reason=(
                        f"Fewer than {MIN_PRIOR_TRIPS} earlier synthetic trips "
                        "for this supplier."
                    ),
                )
            )
            continue
        values = _values_from_prior(trip, prior, lead_times[trip.supplier_id])
        rows.append(
            FeatureRow(
                trip_id=trip.id,
                supplier_id=trip.supplier_id,
                departed_on=trip.departed.isoformat(),
                late=trip.late,
                values=values,
                included=True,
                exclusion_reason="",
            )
        )
    return rows


def features_for_departure(
    *,
    history: list[ShipmentHistoryTrip],
    lead_times: dict[str, int],
    shipment_id: str,
    supplier_id: str,
    origin: str,
    destination: str,
    departed_on: date,
    eta: date,
) -> tuple[dict[str, float] | None, str]:
    """Features for an operational shipment that has already departed.

    The shipment itself is never one of the history rows used here.
    Status and arrival are not accepted by this function.
    """
    if supplier_id not in lead_times:
        return None, "Not scored. This shipment's supplier has no stored lead time."
    if eta < departed_on:
        return None, "Not scored. The expected arrival is earlier than the departure date."
    parsed = [_parse_trip(trip, lead_times) for trip in history]
    prior = _earlier_trips(parsed, supplier_id, departed_on, ignore_id=shipment_id)
    if len(prior) < MIN_PRIOR_TRIPS:
        return (
            None,
            "Not scored. Fewer than 3 earlier synthetic trips for this supplier "
            "depart before this shipment.",
        )
    # arrived is required by the parsed-trip shape. _values_from_prior does not read it.
    stand_in = ParsedTrip(
        id=shipment_id,
        supplier_id=supplier_id,
        origin=origin,
        destination=destination,
        departed=departed_on,
        eta=eta,
        arrived=eta,
    )
    return _values_from_prior(stand_in, prior, lead_times[supplier_id]), ""


def feature_matrix(rows: list[FeatureRow]) -> list[list[float]]:
    """Return allow-listed values in a fixed column order."""
    matrix: list[list[float]] = []
    for row in rows:
        if not row.included:
            raise ValueError(f"{row.trip_id} is excluded and cannot be a model row.")
        unknown = set(row.values) - set(FEATURE_COLUMNS)
        missing = [name for name in FEATURE_COLUMNS if name not in row.values]
        if unknown or missing or set(row.values) & FORBIDDEN_FEATURE_NAMES:
            raise ValueError(f"{row.trip_id} features are not the allow-list.")
        matrix.append([float(row.values[name]) for name in FEATURE_COLUMNS])
    return matrix


def _parse_trip(trip: ShipmentHistoryTrip, lead_times: dict[str, int]) -> ParsedTrip:
    if trip.supplier_id not in lead_times:
        raise ValueError(f"{trip.id} supplier {trip.supplier_id} has no lead time.")
    departed = _parse_date(trip.departed_on, f"{trip.id} departed_on")
    eta = _parse_date(trip.eta, f"{trip.id} eta")
    arrived = _parse_date(trip.arrived_on, f"{trip.id} arrived_on")
    if eta < departed:
        raise ValueError(f"{trip.id} eta is earlier than departed_on.")
    if arrived < departed:
        raise ValueError(f"{trip.id} arrived_on is earlier than departed_on.")
    return ParsedTrip(
        id=trip.id,
        supplier_id=trip.supplier_id,
        origin=trip.origin,
        destination=trip.destination,
        departed=departed,
        eta=eta,
        arrived=arrived,
    )


def _earlier_trips(
    trips: list[ParsedTrip],
    supplier_id: str,
    departed_on: date,
    ignore_id: str,
) -> list[ParsedTrip]:
    """Completed trips for this supplier that departed on an earlier date.

    The current id is ignored even if a caller also passed it in the history.
    A trip that departed on the same date is not earlier.
    """
    return [
        other
        for other in trips
        if other.supplier_id == supplier_id
        and other.id != ignore_id
        and other.departed < departed_on
    ]


def _values_from_prior(
    trip: ParsedTrip,
    prior: list[ParsedTrip],
    lead_time_days: int,
) -> dict[str, float]:
    late_prior = sum(other.late for other in prior)
    values = {
        "supplier_lead_time_days": float(lead_time_days),
        "planned_transit_days": float((trip.eta - trip.departed).days),
        "same_city": 1.0 if trip.origin.casefold() == trip.destination.casefold() else 0.0,
        "supplier_prior_late_rate": late_prior / len(prior),
        "supplier_prior_trip_count": float(len(prior)),
    }
    unknown = set(values) - set(FEATURE_COLUMNS)
    missing = [name for name in FEATURE_COLUMNS if name not in values]
    if unknown or missing or set(values) & FORBIDDEN_FEATURE_NAMES:
        raise ValueError(f"{trip.id} features are not the allow-list.")
    return values


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a YYYY-MM-DD date, got {value!r}.") from exc
