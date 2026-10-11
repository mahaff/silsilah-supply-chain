"""SQLite tables shared by both regional databases.

The same schema is applied to the Saudi Arabia file and the Pakistan file.
Isolation comes from using two files, not from a region column that joins them.
"""

# Money uses integers of minor units (halalas or paisas) so prices are not
# stored as binary floating-point values.
SCHEMA_SQL = """
CREATE TABLE app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region_code TEXT NOT NULL
);

CREATE TABLE supply_chains (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL
);

CREATE TABLE suppliers (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 0)
);

CREATE TABLE products (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL,
    UNIQUE (supply_chain_id, sku)
);

CREATE TABLE warehouses (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    name TEXT NOT NULL,
    city TEXT NOT NULL
);

CREATE TABLE inventory (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    on_hand INTEGER NOT NULL CHECK (on_hand >= 0),
    reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
    UNIQUE (warehouse_id, product_id)
);

CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
    status TEXT NOT NULL CHECK (status IN ('open', 'partial', 'closed')),
    ordered_on TEXT NOT NULL,
    expected_on TEXT NOT NULL
);

CREATE TABLE purchase_order_lines (
    id TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost_minor INTEGER NOT NULL CHECK (unit_cost_minor > 0),
    currency TEXT NOT NULL
);

CREATE TABLE shipments (
    id TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'in_transit', 'delayed', 'delivered')),
    departed_on TEXT,
    eta TEXT NOT NULL,
    arrived_on TEXT
);

-- Created empty. MVP 1 does not invent regulatory rows.
CREATE TABLE governance_references (
    id TEXT PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    authority TEXT NOT NULL,
    regulation_reference TEXT NOT NULL,
    requirement TEXT NOT NULL,
    applicability TEXT NOT NULL,
    source_url TEXT NOT NULL,
    date_verified TEXT NOT NULL,
    implementation_status TEXT NOT NULL,
    technical_control_id TEXT
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    risk_id TEXT,
    rule_id TEXT
);

-- Synthetic issue history used only for days-of-coverage estimates.
CREATE TABLE demand_history (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    quantity_issued INTEGER NOT NULL CHECK (quantity_issued > 0)
);

-- Completed synthetic trips for the predictive demonstration only.
-- The risk register, metrics, and supplier indicators do not read this table.
CREATE TABLE shipment_history (
    id TEXT PRIMARY KEY,
    supply_chain_id TEXT NOT NULL REFERENCES supply_chains(id),
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departed_on TEXT NOT NULL,
    eta TEXT NOT NULL,
    arrived_on TEXT NOT NULL
);

-- One investigation report per subject fingerprint. Drafting does not review a risk.
CREATE TABLE investigations (
    id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('risk', 'estimate')),
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'accepted', 'dismissed', 'stale')),
    evidence_fingerprint TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    actor TEXT NOT NULL
);

-- Review status is kept by stable risk id. The evidence fingerprint decides
-- whether a reviewed or resolved status still applies after a recalculation.
CREATE TABLE risk_reviews (
    risk_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('open', 'reviewed', 'resolved')),
    evidence_fingerprint TEXT NOT NULL,
    actor TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    re_review_required INTEGER NOT NULL CHECK (re_review_required IN (0, 1)),
    re_review_note TEXT NOT NULL
);
"""
