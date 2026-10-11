"""Deterministic risk register for the active region.

Counts are open risks only. Reviewed and resolved rows stay in the table.
The as-of date shown here is the synthetic dataset date, not today's date.
"""

import reflex as rx

from app.components.tip import tip
from app.state import WarRoomState
from app.style import AMBER_BG, AMBER_INK, CARD, INK, KSA, LINE, MUTED, SANS, SERIF


def risk_register() -> rx.Component:
    return rx.vstack(
        rx.heading("Risk register", size="5", color=INK, font_family=SERIF, margin_top="2"),
        rx.text(
            "These alerts are deterministic rules on synthetic data. "
            "They are not predictions, probabilities, or compliance findings.",
            color=MUTED,
            font_family=SANS,
        ),
        rx.text(
            "Synthetic dataset as-of date: ",
            WarRoomState.dataset_as_of,
            ". Overdue checks use this date. It is not today's date.",
            color=INK,
            font_family=SANS,
        ),
        rx.grid(
            _count_card("Open risks", WarRoomState.open_risk_count),
            _count_card("Inventory", WarRoomState.inventory_risk_count),
            _count_card("Shipment", WarRoomState.shipment_risk_count),
            _count_card("Supplier", WarRoomState.supplier_risk_count),
            _count_card("Attention", WarRoomState.attention_risk_count),
            _count_card("Watch", WarRoomState.watch_risk_count),
            columns=rx.breakpoints(initial="2", sm="3", lg="6"),
            spacing="3",
            width="100%",
        ),
        rx.text(
            "Open means not yet reviewed or resolved. Category and severity counts above are open risks only.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        rx.cond(
            WarRoomState.risks.length() == 0,
            rx.text("No deterministic alerts for this supply chain.", color=INK),
            _risk_table(),
        ),
        _risk_detail(),
        rx.heading("Supplier indicators", size="4", color=INK, font_family=SERIF, margin_top="2"),
        rx.text(
            "Counts from this region's synthetic orders and shipments. "
            "A delay proportion is shown only when a supplier has at least three linked shipments. "
            "Otherwise the evidence is insufficient. These are not reliability scores.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        _indicator_table(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _count_card(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(label, color=MUTED, font_size="13px", font_family=SANS),
        rx.heading(value, size="6", color=INK, font_family=SERIF),
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_radius="12px",
        padding="3",
        width="100%",
    )


def _risk_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Risk"),
                    rx.table.column_header_cell("Category"),
                    rx.table.column_header_cell("Severity"),
                    rx.table.column_header_cell("Status"),
                    rx.table.column_header_cell("Re-review"),
                    rx.table.column_header_cell(""),
                ),
            ),
            rx.table.body(
                rx.foreach(WarRoomState.risks, _risk_row),
            ),
            width="100%",
            variant="surface",
            min_width="720px",
        ),
        overflow_x="auto",
        width="100%",
    )


def _risk_row(row: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row["title"]),
        rx.table.cell(row["category_label"]),
        rx.table.cell(row["severity_label"]),
        rx.table.cell(row["status_label"]),
        rx.table.cell(row["re_review"]),
        rx.table.cell(
            rx.button(
                "Inspect",
                on_click=WarRoomState.select_risk(row["id"]),
                size="1",
                variant="outline",
                cursor="pointer",
            )
        ),
    )


def _risk_detail() -> rx.Component:
    return rx.cond(
        WarRoomState.selected_risk_id == "",
        rx.text(
            "Select Inspect on a row to see the rule and the stored values that triggered it.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        rx.box(
            rx.heading(WarRoomState.selected_title, size="4", color=INK, font_family=SERIF),
            rx.text("Status: ", WarRoomState.selected_status, color=INK, margin_top="2", font_family=SANS),
            rx.text("Rule: ", WarRoomState.selected_rule_id, color=KSA, font_family=SANS),
            rx.text(WarRoomState.selected_severity_reason, color=MUTED, font_size="14px", font_family=SANS),
            rx.text(WarRoomState.selected_explanation, color=INK, margin_top="2", font_family=SANS),
            rx.text("Related records", color=MUTED, font_size="13px", margin_top="3"),
            rx.text(WarRoomState.selected_entities, color=INK, font_family=SANS),
            rx.text("Evidence", color=MUTED, font_size="13px", margin_top="3"),
            rx.text(
                WarRoomState.selected_evidence,
                color=INK,
                font_family=SANS,
                white_space="pre-wrap",
            ),
            rx.cond(
                WarRoomState.selected_rereview != "",
                rx.box(
                    rx.text(WarRoomState.selected_rereview, color=AMBER_INK, font_family=SANS),
                    background_color=AMBER_BG,
                    border_radius="12px",
                    padding="3",
                    margin_top="3",
                ),
                rx.fragment(),
            ),
            rx.flex(
                tip(
                    rx.button(
                        "Investigate",
                        on_click=WarRoomState.investigate_selected,
                        variant="outline",
                        cursor="pointer",
                    ),
                    "Draft a read-only report from this risk. It does not mark the risk reviewed or resolved.",
                ),
                rx.button(
                    "Mark reviewed",
                    on_click=WarRoomState.mark_reviewed,
                    variant="outline",
                    cursor="pointer",
                ),
                rx.button(
                    "Mark resolved",
                    on_click=WarRoomState.mark_resolved,
                    color_scheme="teal",
                    cursor="pointer",
                ),
                gap="3",
                wrap="wrap",
                margin_top="4",
            ),
            rx.text(
                "Changing status writes an audit row in this region's database. "
                "The evidence above is kept.",
                color=MUTED,
                font_size="13px",
                margin_top="2",
                font_family=SANS,
            ),
            background_color=CARD,
            border=f"1px solid {LINE}",
            border_radius="16px",
            padding="4",
            width="100%",
        ),
    )


def _indicator_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Supplier"),
                    rx.table.column_header_cell("Delayed shipments"),
                    rx.table.column_header_cell("Linked shipments"),
                    rx.table.column_header_cell("Delay proportion"),
                    rx.table.column_header_cell("Order share"),
                ),
            ),
            rx.table.body(
                rx.foreach(
                    WarRoomState.supplier_indicators,
                    lambda row: rx.table.row(
                        rx.table.cell(row["supplier_name"]),
                        rx.table.cell(row["delayed_shipment_count"]),
                        rx.table.cell(row["linked_shipment_count"]),
                        rx.table.cell(row["delay_proportion_text"]),
                        rx.table.cell(row["order_share_text"]),
                    ),
                ),
            ),
            width="100%",
            variant="surface",
            min_width="720px",
        ),
        overflow_x="auto",
        width="100%",
    )
