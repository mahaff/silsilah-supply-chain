"""Screen picture for ports, families, and Gulf-port quantities.

The numbers are counts from the region already loaded. The Strait of Hormuz
marker is a drawn sea gate for Gulf ports in that file. It is not a vessel
feed and not a political assessment.
"""

from domain.models import InventoryRow, Product, PurchaseOrderLine, Shipment, Supplier

GULF_CITIES = frozenset({"Dammam", "Jubail"})

FAMILY_BY_CATEGORY = {
    "Beverages": "Consumer",
    "Staples": "Consumer",
    "Household": "Consumer",
    "Automotive": "Industry",
    "Packaging": "Industry",
    "Electronics": "Industry",
    "Pharmaceuticals": "Pharmaceuticals",
    "Aerospace & Defense": "Aerospace & Defense",
}

FAMILY_NOTES = {
    "Consumer": "Beverages, staples, and household goods in this synthetic file.",
    "Industry": "Automotive, packaging, and electronics rows in this synthetic file.",
    "Pharmaceuticals": (
        "Pharmaceuticals is the supply-chain name for medicine. "
        "On-hand units are tablets and IV fluids in this synthetic file."
    ),
    "Aerospace & Defense": (
        "Aerospace & Defense is the supply-chain name for defense materiel. "
        "On-hand units are synthetic spares and equipment. "
        "This screen does not describe how controlled goods are made."
    ),
}

FAMILY_ORDER = ("Consumer", "Industry", "Pharmaceuticals", "Aerospace & Defense")

# Positions are percentages on the drawn map, not a navigation chart.
PORTS = (
    {"name": "Jeddah", "x": "22%", "y": "58%", "water": "Red Sea"},
    {"name": "Riyadh", "x": "33%", "y": "46%", "water": "Inland"},
    {"name": "Jubail", "x": "41%", "y": "34%", "water": "Gulf"},
    {"name": "Dammam", "x": "43%", "y": "42%", "water": "Gulf"},
    {"name": "Strait of Hormuz", "x": "52%", "y": "40%", "water": "Chokepoint"},
    {"name": "Karachi", "x": "72%", "y": "58%", "water": "Arabian Sea"},
    {"name": "Faisalabad", "x": "76%", "y": "40%", "water": "Inland"},
    {"name": "Lahore", "x": "80%", "y": "36%", "water": "Inland"},
    {"name": "Islamabad", "x": "78%", "y": "28%", "water": "Inland"},
)


def build_picture(
    products: list[Product],
    inventory: list[InventoryRow],
    lines: list[PurchaseOrderLine],
    shipments: list[Shipment],
    suppliers: list[Supplier],
) -> dict:
    """Return display rows for the map, the family tiles, and the two charts."""
    mentioned = _mentioned_cities(shipments, suppliers)
    gulf_orders = _gulf_order_ids(shipments)
    on_hand = _on_hand_by_category(products, inventory)
    gulf_qty = _gulf_quantity_by_category(products, lines, gulf_orders)
    categories = _category_rows(on_hand, gulf_qty)
    families = _family_rows(on_hand)
    gulf_shipments = sum(1 for shipment in shipments if _touches_gulf(shipment))
    return {
        "ports": [_port(spec, mentioned) for spec in PORTS],
        "categories": categories,
        "families": families,
        "gulf_shipments": gulf_shipments,
        "shipment_count": len(shipments),
        "gulf_note": _gulf_note(gulf_shipments, len(shipments)),
    }


def _mentioned_cities(shipments: list[Shipment], suppliers: list[Supplier]) -> set[str]:
    names = {supplier.city for supplier in suppliers}
    for shipment in shipments:
        names.add(shipment.origin)
        names.add(shipment.destination)
    return names


def _touches_gulf(shipment: Shipment) -> bool:
    return shipment.origin in GULF_CITIES or shipment.destination in GULF_CITIES


def _gulf_order_ids(shipments: list[Shipment]) -> set[str]:
    return {shipment.purchase_order_id for shipment in shipments if _touches_gulf(shipment)}


def _on_hand_by_category(products: list[Product], inventory: list[InventoryRow]) -> dict[str, int]:
    category_of = {product.id: product.category for product in products}
    totals: dict[str, int] = {product.category: 0 for product in products}
    for row in inventory:
        category = category_of.get(row.product_id)
        if category is None:
            continue
        totals[category] = totals.get(category, 0) + row.on_hand
    return totals


def _gulf_quantity_by_category(
    products: list[Product],
    lines: list[PurchaseOrderLine],
    gulf_orders: set[str],
) -> dict[str, int]:
    category_of = {product.id: product.category for product in products}
    totals: dict[str, int] = {product.category: 0 for product in products}
    for line in lines:
        if line.purchase_order_id not in gulf_orders:
            continue
        category = category_of.get(line.product_id)
        if category is None:
            continue
        totals[category] = totals.get(category, 0) + line.quantity
    return totals


def _category_rows(on_hand: dict[str, int], gulf_qty: dict[str, int]) -> list[dict[str, str]]:
    hand_max = max(on_hand.values(), default=0)
    gulf_max = max(gulf_qty.values(), default=0)
    rows: list[dict[str, str]] = []
    for category in sorted(on_hand):
        hand = on_hand[category]
        gulf = gulf_qty.get(category, 0)
        family = FAMILY_BY_CATEGORY.get(category, "Industry")
        rows.append(
            {
                "name": category,
                "family": family,
                "on_hand": str(hand),
                "on_hand_width": _width(hand, hand_max),
                "gulf_quantity": str(gulf),
                "gulf_width": _width(gulf, gulf_max),
                "note": (
                    f"{category} is in the {family} family. "
                    f"On hand {hand}. Order quantity on a Gulf-port lane: {gulf}."
                ),
            }
        )
    return rows


def _family_rows(on_hand: dict[str, int]) -> list[dict[str, str]]:
    totals = {name: 0 for name in FAMILY_ORDER}
    for category, quantity in on_hand.items():
        family = FAMILY_BY_CATEGORY.get(category)
        if family is None:
            continue
        totals[family] += quantity
    peak = max(totals.values(), default=0)
    return [
        {
            "name": name,
            "on_hand": str(totals[name]),
            "width": _width(totals[name], peak),
            "note": FAMILY_NOTES[name],
        }
        for name in FAMILY_ORDER
    ]


def _port(spec: dict[str, str], mentioned: set[str]) -> dict[str, str]:
    name = spec["name"]
    chokepoint = spec["water"] == "Chokepoint"
    gulf = spec["water"] == "Gulf" or chokepoint
    in_file = name in mentioned
    if chokepoint:
        note = (
            "Strait of Hormuz. Gulf ports on this drawing sit west of this strait. "
            "The marker blinks as a corridor watch. It is not a live ship and not a political determination."
        )
    elif in_file:
        note = f"{name} appears on a supplier or shipment row in this region's file. Water: {spec['water']}."
    else:
        note = f"{name} is drawn for orientation. This region's file does not name it."
    return {
        "name": name,
        "x": spec["x"],
        "y": spec["y"],
        "water": spec["water"],
        "blink": "yes" if gulf else "no",
        "in_file": "yes" if in_file else "no",
        "note": note,
    }


def _gulf_note(gulf_shipments: int, shipment_count: int) -> str:
    return (
        f"{gulf_shipments} of {shipment_count} stored shipments name Dammam or Jubail. "
        "Those ports sit inside the Gulf, west of the Strait of Hormuz. "
        "Nothing here is a vessel position."
    )


def _width(value: int, peak: int) -> str:
    if value <= 0 or peak <= 0:
        return "0%"
    return f"{max(8, round(100 * value / peak))}%"
