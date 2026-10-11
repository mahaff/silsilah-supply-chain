"""Synthetic late-arrival estimates. Separate from the deterministic risk register."""

import reflex as rx

from app.components.tip import tip
from app.state import WarRoomState
from app.style import CARD, INK, LINE, MUTED, SANS, SERIF


def prediction_panel() -> rx.Component:
    return rx.vstack(
        rx.heading(
            "Predictive risk",
            size="5",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        rx.text(
            "The risk register applies deterministic rules to known conditions. "
            "Predictive risk is a separate synthetic ML demonstration: an ML estimate "
            "based on synthetic historical shipments.",
            color=INK,
            font_family=SANS,
        ),
        rx.text(WarRoomState.prediction_disclaimer, color=MUTED, font_family=SANS),
        rx.text(
            "Target: ",
            WarRoomState.prediction_target,
            color=INK,
            font_family=SANS,
        ),
        rx.text(
            "Synthetic dataset as-of date: ",
            WarRoomState.dataset_as_of,
            ". The model is logistic regression, retrained in memory from this region's "
            "synthetic history when the page loads. No model file is saved. "
            "Evidence label: ML prediction.",
            color=INK,
            font_family=SANS,
        ),
        rx.text(WarRoomState.prediction_counts, color=INK, font_family=SANS),
        rx.heading(
            "Chronological evaluation",
            size="4",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        rx.text(
            "Primary evaluation. Earlier synthetic trips are the training block and "
            "later trips are the test block.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        rx.text(WarRoomState.prediction_chrono_text, color=INK, font_family=SANS),
        rx.heading(
            "Random-split check",
            size="4",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        rx.text(
            "Secondary check only. Stratified shuffle with random_state 42. "
            "This check is not time-ordered. A later trip in the training fold may "
            "include an earlier trip that the split placed in the test fold. "
            "Features for any one trip still use only earlier departures.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        rx.text(WarRoomState.prediction_random_text, color=INK, font_family=SANS),
        rx.heading(
            "Operational shipments",
            size="4",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        rx.text(WarRoomState.prediction_operational_note, color=INK, font_family=SANS),
        rx.foreach(WarRoomState.prediction_estimates, _estimate_card),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _estimate_card(row: dict) -> rx.Component:
    return rx.box(
        rx.text(row["shipment_id"], color=MUTED, font_size="13px", font_family=SANS),
        rx.heading(row["outcome"], size="4", color=INK, font_family=SERIF),
        rx.cond(
            row["probability"] != "",
            rx.text(
                "Probability: ",
                row["probability"],
                color=INK,
                font_family=SANS,
            ),
            rx.fragment(),
        ),
        rx.cond(
            row["sentence"] != "",
            rx.text(row["sentence"], color=INK, font_family=SANS),
            rx.fragment(),
        ),
        rx.cond(
            row["reason"] != "",
            rx.text(row["reason"], color=MUTED, font_family=SANS),
            rx.fragment(),
        ),
        rx.cond(
            row["factors"] != "",
            rx.text(
                row["factors"],
                color=INK,
                font_family=SANS,
                white_space="pre-wrap",
                margin_top="2",
            ),
            rx.fragment(),
        ),
        rx.cond(
            row["probability"] != "",
            tip(
                rx.button(
                    "Investigate",
                    on_click=WarRoomState.investigate_estimate(row["shipment_id"]),
                    variant="outline",
                    cursor="pointer",
                    margin_top="3",
                ),
                "Draft a report for this estimate. The probability and the deterministic rule stay separate.",
            ),
            rx.fragment(),
        ),
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_radius="12px",
        padding="3",
        width="100%",
    )
