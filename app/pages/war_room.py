"""The single MVP page: one regional supply chain at a time."""

import reflex as rx

from app.components.data_tables import data_tables
from app.components.governance_panel import governance_panel
from app.components.metric_cards import metric_cards
from app.components.risk_register import risk_register
from app.components.region_banner import page_intro, region_banner, region_switch
from app.state import WarRoomState
from app.style import INK, MUTED, PAGE_BG, SANS, SERIF


def war_room_page() -> rx.Component:
    return rx.box(
        rx.box(
            page_intro(),
            region_switch(),
            rx.box(region_banner(), margin_top="4"),
            rx.cond(
                WarRoomState.error_message != "",
                rx.callout.root(
                    rx.callout.text(WarRoomState.error_message),
                    color_scheme="red",
                    margin_top="4",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                WarRoomState.loading,
                rx.text(
                    "Loading the regional database...",
                    color=MUTED,
                    margin_top="5",
                    font_family=SANS,
                ),
                _loaded_body(),
            ),
            rx.text(
                "Local only. No purchasing, payments, messages, or other external actions.",
                color=MUTED,
                font_size="14px",
                margin_top="6",
                font_family=SANS,
            ),
            max_width="1120px",
            margin_x="auto",
            padding_x="4",
            padding_y="6",
        ),
        background_color=PAGE_BG,
        min_height="100vh",
        color=INK,
    )


def _loaded_body() -> rx.Component:
    return rx.vstack(
        rx.heading(
            "Supply chain snapshot",
            size="5",
            color=INK,
            font_family=SERIF,
            margin_top="5",
        ),
        rx.text(
            "Counts are for the supply chain named above. "
            "A database fact is a straight count. A deterministic rule keeps rows that match a condition.",
            color=MUTED,
            font_family=SANS,
        ),
        metric_cards(),
        risk_register(),
        rx.heading(
            "Records",
            size="5",
            color=INK,
            font_family=SERIF,
            margin_top="2",
        ),
        data_tables(),
        governance_panel(),
        spacing="4",
        width="100%",
        align_items="start",
    )
