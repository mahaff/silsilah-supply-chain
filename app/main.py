"""Reflex entry point.

rxconfig.py loads this module and expects a variable named app.
Importing the page here is what makes Reflex include it.
"""

import reflex as rx

from app.pages.war_room import war_room_page
from app.state import WarRoomState
from app.style import PAGE_BG, SANS

app = rx.App(
    style={
        "font_family": SANS,
        "background_color": PAGE_BG,
    },
)
app.add_page(
    war_room_page,
    route="/",
    title="Silsilah",
    description="Agentic Supply Chain Intelligence & Governance Platform",
    on_load=WarRoomState.load_region,
)
