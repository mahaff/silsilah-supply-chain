"""Tables for the five operational lists in the active supply chain."""

import reflex as rx

from app.state import WarRoomState
from app.style import INK, MUTED, SANS


def data_tables() -> rx.Component:
    return rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("Suppliers", value="suppliers"),
            rx.tabs.trigger("Products", value="products"),
            rx.tabs.trigger("Inventory", value="inventory"),
            rx.tabs.trigger("Purchase orders", value="orders"),
            rx.tabs.trigger("Shipments", value="shipments"),
            wrap="wrap",
        ),
        rx.tabs.content(_suppliers(), value="suppliers", padding_top="4"),
        rx.tabs.content(_products(), value="products", padding_top="4"),
        rx.tabs.content(_inventory(), value="inventory", padding_top="4"),
        rx.tabs.content(_orders(), value="orders", padding_top="4"),
        rx.tabs.content(_shipments(), value="shipments", padding_top="4"),
        default_value="suppliers",
        width="100%",
    )


def _suppliers() -> rx.Component:
    return _table_block(
        "Fictional suppliers for this supply chain.",
        WarRoomState.suppliers,
        ("Supplier", "City", "Status", "Lead time (days)"),
        ("name", "city", "status", "lead_time_days"),
        "No suppliers in this synthetic dataset.",
    )


def _products() -> rx.Component:
    return _table_block(
        "Fictional products. SKUs are different in each region.",
        WarRoomState.products,
        ("SKU", "Product", "Category", "Unit"),
        ("sku", "name", "category", "unit"),
        "No products in this synthetic dataset.",
    )


def _inventory() -> rx.Component:
    return _table_block(
        "Below reorder is Yes only when on-hand quantity is lower than the reorder point.",
        WarRoomState.inventory,
        ("Warehouse", "SKU", "Product", "On hand", "Reorder point", "Below reorder"),
        ("warehouse_name", "sku", "product_name", "on_hand", "reorder_point", "below_reorder"),
        "No inventory rows in this synthetic dataset.",
    )


def _orders() -> rx.Component:
    return rx.vstack(
        _table_block(
            "These orders are records in the synthetic database. Nothing is purchased.",
            WarRoomState.orders,
            ("Order", "Supplier", "Warehouse", "Status", "Ordered", "Expected"),
            ("id", "supplier_name", "warehouse_name", "status", "ordered_on", "expected_on"),
            "No purchase orders in this synthetic dataset.",
        ),
        rx.text(
            WarRoomState.order_line_count,
            " order lines are stored for this supply chain. "
            "Prices are whole minor currency units (",
            WarRoomState.currency,
            "), not a live price feed.",
            color=MUTED,
            font_size="14px",
            font_family=SANS,
        ),
        align_items="start",
        width="100%",
        spacing="3",
    )


def _shipments() -> rx.Component:
    return _table_block(
        "Shipment status is a stored label. The app does not track live vehicles.",
        WarRoomState.shipments,
        ("Shipment", "Order", "Origin", "Destination", "Status", "Departed", "ETA", "Arrived"),
        (
            "id",
            "purchase_order_id",
            "origin",
            "destination",
            "status",
            "departed_on",
            "eta",
            "arrived_on",
        ),
        "No shipments in this synthetic dataset.",
    )


def _table_block(caption: str, rows, headers: tuple[str, ...], keys: tuple[str, ...], empty: str) -> rx.Component:
    return rx.vstack(
        rx.text(caption, color=MUTED, font_size="14px", font_family=SANS),
        rx.cond(
            rows.length() == 0,
            rx.text(empty, color=INK, padding_y="4"),
            rx.box(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            *[rx.table.column_header_cell(header) for header in headers]
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            rows,
                            lambda row: rx.table.row(
                                *[rx.table.cell(row[key]) for key in keys]
                            ),
                        ),
                    ),
                    width="100%",
                    variant="surface",
                    min_width="720px",
                ),
                overflow_x="auto",
                width="100%",
            ),
        ),
        align_items="start",
        width="100%",
        spacing="3",
    )
