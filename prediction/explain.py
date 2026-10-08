"""Plain-language notes for logistic-regression contributions.

Wording stays descriptive. It does not say a supplier caused a delay or
that a shipment will be late.
"""

from pydantic import BaseModel, ConfigDict

from prediction.features import FEATURE_COLUMNS

FEATURE_PHRASES: dict[str, str] = {
    "supplier_lead_time_days": "The supplier's stored lead time",
    "planned_transit_days": "The planned transit length",
    "same_city": "Whether the origin and destination are the same city",
    "supplier_prior_late_rate": (
        "The share of this supplier's earlier synthetic trips that arrived "
        "after the expected date"
    ),
    "supplier_prior_trip_count": "The number of this supplier's earlier synthetic trips",
}

_BANNED_PHRASES: tuple[str, ...] = (
    "supplier caused the delay",
    "this supplier will be late",
    "the shipment will definitely be delayed",
    "caused the delay",
    "definitely",
    "will be late",
)


class Contribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str
    raw_value: float
    contribution: float
    sentence: str


def explain_contributions(
    *,
    coefficients: list[float],
    scaled_values: list[float],
    raw_values: dict[str, float],
) -> list[Contribution]:
    """Return the three features with the largest absolute contribution.

    Contribution is the scaled feature value times that feature's coefficient.
    """
    if len(coefficients) != len(FEATURE_COLUMNS) or len(scaled_values) != len(FEATURE_COLUMNS):
        raise ValueError("Contributions need one coefficient per allow-listed feature.")
    parts: list[Contribution] = []
    for name, coefficient, scaled in zip(FEATURE_COLUMNS, coefficients, scaled_values, strict=True):
        contribution = float(scaled) * float(coefficient)
        sentence = _guard(_sentence(name, contribution))
        parts.append(
            Contribution(
                feature=name,
                raw_value=float(raw_values[name]),
                contribution=contribution,
                sentence=sentence,
            )
        )
    parts.sort(key=lambda item: (-abs(item.contribution), item.feature))
    return parts[:3]


def probability_sentence(probability: float) -> str:
    """State the estimate without calling it certain."""
    text = (
        f"The model estimates a {probability:.2f} probability of arriving "
        "after the expected date. This is an estimate based on synthetic "
        "historical data, not a real-world forecast."
    )
    return _guard(text)


def _sentence(feature: str, contribution: float) -> str:
    phrase = FEATURE_PHRASES[feature]
    if contribution > 0:
        direction = "increased the model estimate"
    elif contribution < 0:
        direction = "decreased the model estimate"
    else:
        direction = "did not change the model estimate"
    return f"{phrase} {direction} (contribution {contribution:+.3f})."


def _guard(text: str) -> str:
    lowered = text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            raise ValueError("Explanation wording is not allowed.")
    return text
