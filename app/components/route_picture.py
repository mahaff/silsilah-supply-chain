"""Drawn ports, family tiles, and Gulf-port quantities for the open region."""

import reflex as rx

from app.components.tip import tip
from app.state import WarRoomState
from app.style import CARD, DANGER, GULF, INK, LINE, MAP_BG, MUTED, SANS, SEA

_MAP = """
<svg viewBox="0 0 760 420" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Drawn sea lanes">
  <rect width="760" height="420" fill="#102733"/>
  <path fill="#173244" d="M90 70h250l70 50 20 70-40 40-30 90-120 30-110-90z"/>
  <path fill="#173244" d="M390 48h150l-10 70-120 20z"/>
  <path fill="#173244" d="M560 78h150l20 130-80 80-90-40z"/>
  <path d="M430 150c30 8 48 28 52 48" fill="none" stroke="#e0a106" stroke-width="3" stroke-dasharray="5 4"/>
</svg>
"""


def route_picture() -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.box(
                rx.text(
                    "PORTS",
                    font_size="12px",
                    letter_spacing="0.12em",
                    color=GULF,
                    font_weight="700",
                    font_family=SANS,
                ),
                rx.heading("Corridor picture", size="5", color=INK, margin_top="1"),
            ),
            tip(
                rx.badge("Synthetic drawing", variant="soft", color_scheme="amber"),
                "Blinking dots are Gulf ports and the Strait of Hormuz. They are not live ships.",
            ),
            justify="between",
            align="end",
            width="100%",
            wrap="wrap",
            gap="3",
        ),
        rx.text(WarRoomState.picture_gulf_note, color=MUTED, font_family=SANS),
        rx.grid(
            _map_card(),
            _charts(),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="4",
            width="100%",
        ),
        _families(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _map_card() -> rx.Component:
    return rx.box(
        rx.box(
            rx.html(_MAP),
            rx.foreach(WarRoomState.picture_ports, _port),
            position="relative",
            min_width="640px",
        ),
        overflow_x="auto",
        background_color=MAP_BG,
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="2",
        width="100%",
    )


def _port(port: dict) -> rx.Component:
    return tip(
        rx.box(
            rx.box(
                width="12px",
                height="12px",
                border_radius="999px",
                background_color=rx.cond(
                    port["water"] == "Chokepoint",
                    DANGER,
                    rx.cond(port["blink"] == "yes", GULF, SEA),
                ),
                border=rx.cond(
                    port["in_file"] == "yes",
                    "2px solid white",
                    "2px solid transparent",
                ),
                class_name=rx.cond(port["blink"] == "yes", "port-blink", ""),
            ),
            rx.text(
                port["name"],
                color="white",
                font_size="11px",
                font_family=SANS,
                margin_top="1",
            ),
            position="absolute",
            left=port["x"],
            top=port["y"],
            transform="translate(-50%, -50%)",
            text_align="center",
        ),
        port["note"],
    )


def _charts() -> rx.Component:
    return rx.vstack(
        _bar_card(
            "On hand by category",
            "Sum of stored on-hand units for that category in this file.",
            _on_hand_bar,
        ),
        _bar_card(
            "Gulf-port order quantity",
            "Order quantity whose shipment names Dammam or Jubail. Other lanes stay at zero.",
            _gulf_bar,
        ),
        spacing="3",
        width="100%",
    )


def _bar_card(title: str, hint: str, row_fn) -> rx.Component:
    return rx.box(
        tip(
            rx.heading(title, size="3", color=INK),
            hint,
        ),
        rx.foreach(WarRoomState.picture_categories, row_fn),
        background_color=CARD,
        border=f"1px solid {LINE}",
        border_radius="16px",
        padding="4",
        width="100%",
    )


def _on_hand_bar(row: dict) -> rx.Component:
    return _bar(row, row["on_hand"], row["on_hand_width"], SEA)


def _gulf_bar(row: dict) -> rx.Component:
    return _bar(row, row["gulf_quantity"], row["gulf_width"], DANGER)


def _bar(row: dict, value, width, color: str) -> rx.Component:
    return tip(
        rx.hstack(
            rx.text(
                row["name"],
                width="168px",
                font_size="13px",
                color=INK,
                font_family=SANS,
                flex_shrink="0",
            ),
            rx.box(
                rx.box(
                    width=width,
                    height="8px",
                    border_radius="999px",
                    background_color=color,
                ),
                flex="1",
                background_color="#e7eef2",
                border_radius="999px",
                height="8px",
            ),
            rx.text(value, width="48px", text_align="right", color=MUTED, font_size="13px"),
            width="100%",
            align="center",
            spacing="3",
            padding_y="1",
        ),
        row["note"],
    )


def _families() -> rx.Component:
    return rx.grid(
        rx.foreach(WarRoomState.picture_families, _family),
        columns=rx.breakpoints(initial="2", lg="4"),
        spacing="3",
        width="100%",
    )


def _family(row: dict) -> rx.Component:
    return tip(
        rx.box(
            rx.text(
                row["name"],
                font_size="12px",
                letter_spacing="0.08em",
                color=MUTED,
                font_weight="700",
                font_family=SANS,
            ),
            rx.heading(row["on_hand"], size="6", color=INK, margin_y="1"),
            rx.box(
                rx.box(
                    width=row["width"],
                    height="6px",
                    border_radius="999px",
                    background_color=rx.cond(row["on_hand"] == "0", LINE, SEA),
                ),
                background_color="#e7eef2",
                border_radius="999px",
                height="6px",
            ),
            background_color=CARD,
            border=f"1px solid {LINE}",
            border_radius="16px",
            padding="3",
            width="100%",
        ),
        row["note"],
    )
