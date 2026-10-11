"""One tooltip wrapper so hints stay consistent."""

import reflex as rx


def tip(child: rx.Component, content: rx.Var | str) -> rx.Component:
    return rx.tooltip(child, content=content, side="top")
