"""Region switch and the banner that names the active edition."""

import reflex as rx

from app.state import WarRoomState
from app.style import AMBER_BG, AMBER_INK, CARD, INK, KSA, LINE, MUTED, PAKISTAN, SANS, SERIF, WHITE


def region_switch() -> rx.Component:
    return rx.flex(
        _region_button("Saudi Arabia", "ksa", "teal"),
        _region_button("Pakistan", "pakistan", "blue"),
        gap="3",
        wrap="wrap",
    )


def _region_button(label: str, code: str, color_scheme: str) -> rx.Component:
    selected = WarRoomState.region_code == code
    return rx.button(
        label,
        on_click=WarRoomState.select_region(code),
        variant=rx.cond(selected, "solid", "outline"),
        color_scheme=color_scheme,
        size="3",
        cursor="pointer",
    )


def region_banner() -> rx.Component:
    """A full-width banner so the active region cannot be missed."""
    return rx.box(
        rx.flex(
            rx.box(
                rx.text(
                    "ACTIVE REGION",
                    font_size="12px",
                    letter_spacing="0.08em",
                    color="rgba(255,255,255,0.75)",
                    font_family=SANS,
                ),
                rx.heading(
                    rx.cond(
                        WarRoomState.region_code == "ksa",
                        "Saudi Arabia",
                        "Pakistan",
                    ),
                    size="7",
                    color=WHITE,
                    font_family=SERIF,
                    margin_top="1",
                ),
            ),
            rx.box(
                rx.text(
                    "SYNTHETIC DATA",
                    font_size="12px",
                    font_weight="700",
                    letter_spacing="0.06em",
                    color=AMBER_INK,
                    background_color=AMBER_BG,
                    padding_x="3",
                    padding_y="1",
                    border_radius="999px",
                ),
            ),
            justify="between",
            align="center",
            wrap="wrap",
            gap="3",
        ),
        rx.cond(
            WarRoomState.supply_chain_name == "",
            rx.text(
                "The organization and supply chain load with this region's database.",
                color="rgba(255,255,255,0.85)",
                margin_top="4",
            ),
            rx.vstack(
                rx.text(
                    "Organization: ",
                    WarRoomState.organization_name,
                    color=WHITE,
                    font_family=SANS,
                ),
                rx.text(
                    "Supply chain: ",
                    WarRoomState.supply_chain_name,
                    color=WHITE,
                    font_family=SANS,
                ),
                rx.text(
                    WarRoomState.organization_id,
                    "  ·  ",
                    WarRoomState.supply_chain_id,
                    "  ·  Currency ",
                    WarRoomState.currency,
                    color="rgba(255,255,255,0.75)",
                    font_size="14px",
                ),
                align_items="start",
                spacing="1",
                margin_top="4",
            ),
        ),
        rx.text(
            "All suppliers, products, stock, orders, and shipments on this page are fictional.",
            color="rgba(255,255,255,0.9)",
            margin_top="3",
            font_family=SANS,
        ),
        rx.cond(
            WarRoomState.dataset_as_of != "",
            rx.text(
                "Synthetic dataset as-of date: ",
                WarRoomState.dataset_as_of,
                ". This is not today's date.",
                color="rgba(255,255,255,0.9)",
                margin_top="2",
                font_family=SANS,
            ),
            rx.fragment(),
        ),
        background_color=rx.cond(WarRoomState.region_code == "ksa", KSA, PAKISTAN),
        border_radius="16px",
        padding="5",
        width="100%",
    )


def page_intro() -> rx.Component:
    return rx.box(
        rx.text(
            "SILSILAH",
            font_size="13px",
            letter_spacing="0.14em",
            color=KSA,
            font_weight="700",
        ),
        rx.heading(
            "Silsilah",
            size="8",
            color=INK,
            font_family=SERIF,
            margin_top="1",
        ),
        rx.text(
            "Agentic Supply Chain Intelligence & Governance Platform",
            color=MUTED,
            font_size="18px",
            margin_top="2",
        ),
        rx.text(
            "Pick a region to open its own synthetic supply chain. "
            "Saudi Arabia and Pakistan do not share a database.",
            color=INK,
            margin_top="3",
            max_width="720px",
        ),
        margin_bottom="5",
    )


def card_shell(*children) -> rx.Component:
    return rx.box(
        *children,
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="4",
        width="100%",
    )
