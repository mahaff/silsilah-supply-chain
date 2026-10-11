"""The map picture counts this region's rows, including pharmaceuticals and aerospace."""

from app.picture import build_picture
from persistence.repository import RegionRepository


def test_ksa_picture_uses_gulf_ports_and_counts_pharma_and_aerospace(regional_databases):
    picture = _picture(regional_databases, "ksa")
    assert picture["gulf_shipments"] == 4
    assert picture["shipment_count"] == 6
    families = {row["name"]: row["on_hand"] for row in picture["families"]}
    assert families["Pharmaceuticals"] == "100"
    assert families["Aerospace & Defense"] == "32"
    assert "medicine" in next(
        row["note"] for row in picture["families"] if row["name"] == "Pharmaceuticals"
    )
    assert int(families["Industry"]) > 0
    assert int(families["Consumer"]) > 0
    ports = {row["name"]: row for row in picture["ports"]}
    assert ports["Dammam"]["in_file"] == "yes"
    assert ports["Dammam"]["blink"] == "yes"
    assert ports["Strait of Hormuz"]["blink"] == "yes"
    assert ports["Strait of Hormuz"]["in_file"] == "no"
    assert "not a live ship" in ports["Strait of Hormuz"]["note"]
    gulf = {row["name"]: row["gulf_quantity"] for row in picture["categories"]}
    on_hand = {row["name"]: row["on_hand"] for row in picture["categories"]}
    assert gulf["Packaging"] == "50"
    assert gulf["Automotive"] == "25"
    assert gulf["Staples"] == "0"
    assert gulf["Pharmaceuticals"] == "40"
    assert gulf["Aerospace & Defense"] == "20"
    assert on_hand["Pharmaceuticals"] == "100"
    assert on_hand["Aerospace & Defense"] == "32"


def test_pakistan_picture_has_no_gulf_lane(regional_databases):
    picture = _picture(regional_databases, "pakistan")
    assert picture["gulf_shipments"] == 0
    assert picture["shipment_count"] == 6
    assert all(row["gulf_quantity"] == "0" for row in picture["categories"])
    ports = {row["name"]: row for row in picture["ports"]}
    assert ports["Karachi"]["in_file"] == "yes"
    assert ports["Dammam"]["in_file"] == "no"
    families = {row["name"]: row["on_hand"] for row in picture["families"]}
    assert families["Pharmaceuticals"] == "120"
    assert families["Aerospace & Defense"] == "20"


def _picture(regional_databases, region_code: str) -> dict:
    repository = RegionRepository(region_code, database_path=regional_databases[region_code])
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    return build_picture(
        repository.list_products(chain_id),
        repository.list_inventory(chain_id),
        repository.list_purchase_order_lines(chain_id),
        repository.list_shipments(chain_id),
        repository.list_suppliers(chain_id),
    )
