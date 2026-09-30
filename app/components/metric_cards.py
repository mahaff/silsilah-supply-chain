"""Six metric cards. Each card names whether the number is a fact or a rule."""

import reflex as rx

from app.state import WarRoomState
from app.style import CARD, INK, KSA, LINE, MUTED, SANS, SERIF


def metric_cards() -> rx.Component:
    return rx.grid(
        rx.foreach(WarRoomState.metrics, _metric_card),
        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
        spacing="3",
        width="100%",
    )


def _metric_card(metric: dict) -> rx.Component:
    return rx.box(
        rx.text(metric["label"], color=MUTED, font_size="14px", font_family=SANS),
        rx.heading(
            metric["value"],
            size="8",
            color=INK,
            font_family=SERIF,
            margin_y="2",
        ),
        rx.text(
            metric["evidence_label"],
            color=KSA,
            font_size="12px",
            font_weight="700",
            letter_spacing="0.04em",
        ),
        rx.text(
            metric["explanation"],
            color=MUTED,
            font_size="14px",
            margin_top="2",
            font_family=SANS,
        ),
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_top=f"4px solid {KSA}",
        border_radius="16px",
        padding="4",
        height="100%",
    )
