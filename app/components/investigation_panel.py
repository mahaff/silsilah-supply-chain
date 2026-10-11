"""Investigation report. Accepting it does not review or resolve a risk."""

import reflex as rx

from app.components.tip import tip
from app.state import WarRoomState
from app.style import CARD, INK, LINE, MUTED, SANS, SERIF


def investigation_panel() -> rx.Component:
    return rx.vstack(
        rx.heading(
            "Investigation",
            size="5",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        rx.text(
            "A report restates fields read from this region's database. "
            "It does not place an order, contact a supplier, or change a shipment.",
            color=MUTED,
            font_family=SANS,
        ),
        rx.cond(
            WarRoomState.investigation_id == "",
            rx.text(
                "Choose Investigate on a risk, or on a scored estimate, to draft a report. "
                "Accepting that report does not mark a risk reviewed or resolved.",
                color=INK,
                font_family=SANS,
            ),
            _report(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _report() -> rx.Component:
    return rx.box(
        rx.text(
            "Status: ",
            WarRoomState.investigation_status,
            color=INK,
            font_family=SANS,
        ),
        rx.text(
            "Subject: ",
            WarRoomState.investigation_subject,
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        rx.text(
            "Investigation summary",
            color=MUTED,
            font_size="13px",
            margin_top="3",
            font_family=SANS,
        ),
        rx.text(WarRoomState.investigation_finding, color=INK, font_family=SANS),
        rx.text(
            WarRoomState.investigation_notice,
            color=INK,
            font_family=SANS,
            white_space="pre-wrap",
            margin_top="2",
        ),
        rx.text("Claims", color=MUTED, font_size="13px", margin_top="3", font_family=SANS),
        rx.foreach(WarRoomState.investigation_claims, _claim),
        rx.text("Evidence gaps", color=MUTED, font_size="13px", margin_top="3", font_family=SANS),
        rx.cond(
            WarRoomState.investigation_gap_note != "",
            rx.text(WarRoomState.investigation_gap_note, color=INK, font_family=SANS),
            rx.foreach(WarRoomState.investigation_gaps, _gap),
        ),
        rx.text("Next steps", color=MUTED, font_size="13px", margin_top="3", font_family=SANS),
        rx.foreach(WarRoomState.investigation_steps, _step),
        rx.cond(
            WarRoomState.investigation_status == "draft",
            rx.vstack(
                rx.flex(
                    tip(
                        rx.button(
                            "Accept",
                            on_click=WarRoomState.accept_report,
                            color_scheme="teal",
                            cursor="pointer",
                        ),
                        "Acknowledge this report. The risk status and the operational rows stay as they are.",
                    ),
                    tip(
                        rx.button(
                            "Dismiss",
                            on_click=WarRoomState.dismiss_report,
                            variant="outline",
                            cursor="pointer",
                        ),
                        "Set this report aside. Nothing in the register or the shipment table changes.",
                    ),
                    gap="3",
                    wrap="wrap",
                ),
                rx.text(
                    "Accept means you acknowledge this report. "
                    "It does not mark a risk reviewed or resolved.",
                    color=MUTED,
                    font_size="13px",
                    font_family=SANS,
                ),
                spacing="2",
                align_items="start",
                margin_top="4",
            ),
            rx.fragment(),
        ),
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="4",
        width="100%",
    )


def _claim(row: dict) -> rx.Component:
    return rx.box(
        rx.text(
            row["citation_id"],
            " · ",
            row["evidence_kind"],
            color=MUTED,
            font_size="13px",
            font_family=SANS,
        ),
        rx.text(row["text"], color=INK, font_family=SANS),
        rx.text(
            row["source"],
            ".",
            row["field"],
            " = ",
            row["value"],
            color=MUTED,
            font_size="13px",
            font_family=SANS,
            white_space="pre-wrap",
        ),
        margin_top="2",
        width="100%",
    )


def _gap(row: dict) -> rx.Component:
    return rx.text(row["text"], color=INK, font_family=SANS, margin_top="1")


def _step(row: dict) -> rx.Component:
    return rx.text(row["text"], color=INK, font_family=SANS, margin_top="1")
