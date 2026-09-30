"""Domain model for one regional database.

Future hierarchy, already represented in the data:

    Region -> Organization -> Supply Chain -> operational records

MVP 1 stores one organization and one supply chain in each regional file.
A region is the database file plus its config folder, not a row that mixes
Saudi Arabia and Pakistan together.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class RegionCode(str, Enum):
    KSA = "ksa"
    PAKISTAN = "pakistan"

    @classmethod
    def parse(cls, value: str) -> "RegionCode":
        """Accept only the two regional editions."""
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise ValueError(
                "Choose a region code of 'ksa' or 'pakistan'."
            ) from exc


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"


class ShipmentStatus(str, Enum):
    PLANNED = "planned"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Organization(BaseModel):
    """A fictional company inside one regional database."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    region_code: RegionCode


class SupplyChain(BaseModel):
    """One chain of suppliers, stock, orders, and shipments.

    The id is stored on operational rows so a later edition can hold more
    than one chain without mixing their records.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    organization_id: str
    name: str


class Supplier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    name: str
    city: str
    status: SupplierStatus
    lead_time_days: int = Field(ge=0)


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    sku: str
    name: str
    category: str
    unit: str


class Warehouse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    name: str
    city: str


class InventoryRow(BaseModel):
    """One stock position, with names attached for the screen."""

    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    warehouse_name: str
    sku: str
    product_name: str
    on_hand: int = Field(ge=0)
    reorder_point: int = Field(ge=0)

    @computed_field
    @property
    def below_reorder(self) -> bool:
        """True when the deterministic low-stock rule matches this row."""
        return self.on_hand < self.reorder_point


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    supplier_id: str
    warehouse_id: str
    status: OrderStatus
    ordered_on: str
    expected_on: str


class PurchaseOrderRow(BaseModel):
    """A purchase order plus the names a person needs on screen."""

    model_config = ConfigDict(extra="forbid")

    id: str
    supply_chain_id: str
    supplier_name: str
    warehouse_name: str
    status: OrderStatus
    ordered_on: str
    expected_on: str


class PurchaseOrderLine(BaseModel):
    """A line on an order. Money is an integer of minor currency units."""

    model_config = ConfigDict(extra="forbid")

    id: str
    purchase_order_id: str
    product_id: str
    quantity: int = Field(gt=0)
    unit_cost_minor: int = Field(gt=0)
    currency: str


class Shipment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    purchase_order_id: str
    origin: str
    destination: str
    status: ShipmentStatus
    departed_on: str | None
    eta: str
    arrived_on: str | None


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    occurred_at: str
    actor: str
    action: str
    evidence_kind: str
    summary: str


class RegionScope(BaseModel):
    """The single organization and supply chain MVP 1 is allowed to show."""

    model_config = ConfigDict(extra="forbid")

    organization: Organization
    supply_chain: SupplyChain
    display_name: str
    currency: str
    timezone: str


STATUS_LABELS: dict[str, str] = {
    "open": "Open",
    "partial": "Partial",
    "closed": "Closed",
    "planned": "Planned",
    "in_transit": "In transit",
    "delayed": "Delayed",
    "delivered": "Delivered",
    "active": "Active",
    "inactive": "Inactive",
}


def status_label(value: str) -> str:
    """Turn a stored status token into words for the screen."""
    return STATUS_LABELS.get(value, value)
