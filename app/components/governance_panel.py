"""Governance status and the null reasoning note.

Neither card makes a legal claim. The reasoning card shows that no language
model is connected and that the metrics did not come from one.
"""

import reflex as rx

from app.state import WarRoomState
from app.style import AMBER_BG, AMBER_INK, INK, KSA, LINE, MUTED, SANS, SERIF


def governance_panel() -> rx.Component:
    return rx.grid(
        _governance_card(),
        _reasoning_card(),
        columns=rx.breakpoints(initial="1", lg="2"),
        spacing="4",
        width="100%",
    )


def _governance_card() -> rx.Component:
    return rx.box(
        rx.heading("Governance status", size="5", color=INK, font_family=SERIF),
        rx.text(
            "This area is a placeholder for official references you may add later.",
            color=MUTED,
            margin_top="2",
            font_family=SANS,
        ),
        _fact("Region", WarRoomState.region_display_name),
        _fact("Data classification", WarRoomState.governance_classification),
        _fact("Regulatory references loaded", WarRoomState.governance_references_loaded),
        rx.text(WarRoomState.governance_note, color=INK, margin_top="3", font_family=SANS),
        rx.box(
            rx.text(WarRoomState.governance_disclaimer, color=AMBER_INK, font_family=SANS),
            background_color=AMBER_BG,
            border_radius="12px",
            padding="3",
            margin_top="3",
        ),
        rx.text("Latest audit record", color=MUTED, font_size="13px", margin_top="4"),
        rx.text(WarRoomState.audit_summary, color=INK, font_family=SANS),
        rx.text(WarRoomState.audit_at, color=MUTED, font_size="13px"),
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="4",
        background_color="#fffcf7",
        height="100%",
    )


def _reasoning_card() -> rx.Component:
    return rx.box(
        rx.heading("Reasoning", size="5", color=INK, font_family=SERIF),
        rx.text(
            "Provider: ",
            WarRoomState.reasoning_provider,
            color=KSA,
            font_weight="700",
            margin_top="2",
            font_family=SANS,
        ),
        rx.text(WarRoomState.reasoning_note, color=INK, margin_top="3", font_family=SANS),
        rx.text(
            "Evidence type reserved for a future note: LLM reasoning. "
            "MVP 1 does not use that note to produce any number on this page.",
            color=MUTED,
            margin_top="3",
            font_size="14px",
            font_family=SANS,
        ),
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="4",
        background_color="#fffcf7",
        height="100%",
    )


def _fact(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(label, color=MUTED, font_size="13px", font_family=SANS),
        rx.text(value, color=INK, font_weight="600", font_family=SANS),
        margin_top="3",
    )
