"""The synthetic seed builds one chain and leaves governance empty."""

import sqlite3

from governance.status import build_governance_status
from persistence.repository import RegionRepository


def test_ksa_seed_shape(regional_databases):
    _assert_shape("ksa", regional_databases["ksa"], "KSA", "SAR", "Wadi Demo Distributors")


def test_pakistan_seed_shape(regional_databases):
    _assert_shape(
        "pakistan",
        regional_databases["pakistan"],
        "PAK",
        "PKR",
        "Ravi Demo Distributors",
    )


def test_reseed_replaces_rows(regional_databases):
    path = regional_databases["ksa"]
    from persistence.seed import seed_region

    seed_region("ksa", database_path=path)
    repository = RegionRepository("ksa", database_path=path)
    scope = repository.load_scope()
    assert scope.organization.name == "Wadi Demo Distributors"
    assert len(repository.list_suppliers(scope.supply_chain.id)) == 4


def test_governance_status_makes_no_compliance_claim(regional_databases):
    repository = RegionRepository("ksa", database_path=regional_databases["ksa"])
    status = build_governance_status(
        "Saudi Arabia",
        repository.governance_reference_count(),
        repository.latest_audit_event(),
    )
    assert status.references_loaded == 0
    assert status.data_classification == "Synthetic"
    assert "does not provide legal advice" in status.disclaimer
    assert "does not certify compliance" in status.disclaimer
    assert "none" in status.references_note.lower()


def _assert_shape(region_code, database_path, prefix, currency, organization_name):
    repository = RegionRepository(region_code, database_path=database_path)
    scope = repository.load_scope()
    chain_id = scope.supply_chain.id
    assert scope.organization.name == organization_name
    assert scope.organization.region_code.value == region_code
    assert scope.supply_chain.organization_id == scope.organization.id
    assert chain_id.startswith(prefix)
    assert len(repository.list_suppliers(chain_id)) == 4
    assert len(repository.list_products(chain_id)) == 6
    assert len(repository.list_warehouses(chain_id)) == 2
    assert len(repository.list_inventory(chain_id)) == 8
    assert len(repository.list_purchase_orders(chain_id)) == 5
    assert len(repository.list_purchase_order_lines(chain_id)) == 7
    assert len(repository.list_shipments(chain_id)) == 4
    assert repository.governance_reference_count() == 0

    audit = repository.latest_audit_event()
    assert audit is not None
    assert audit.action == "seed_synthetic_dataset"
    assert "synthetic" in audit.summary.lower()

    for line in repository.list_purchase_order_lines(chain_id):
        assert line.currency == currency
        assert line.unit_cost_minor > 0

    connection = sqlite3.connect(database_path)
    try:
        stored_type = connection.execute(
            "SELECT typeof(unit_cost_minor) AS kind FROM purchase_order_lines LIMIT 1"
        ).fetchone()[0]
        assert stored_type == "integer"
        meta = dict(connection.execute("SELECT key, value FROM app_meta"))
        assert meta["synthetic"] == "true"
        assert meta["dataset_label"] == "synthetic"
        assert meta["region_code"] == region_code
    finally:
        connection.close()
