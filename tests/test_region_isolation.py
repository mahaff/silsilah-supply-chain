"""Saudi Arabia and Pakistan stay in separate database files."""

import pytest

from domain.models import RegionCode
from persistence.connection import load_region_config
from persistence.repository import RegionRepository


def test_region_codes_are_only_the_two_editions():
    assert RegionCode.parse("ksa") is RegionCode.KSA
    assert RegionCode.parse("Pakistan") is RegionCode.PAKISTAN
    with pytest.raises(ValueError):
        RegionCode.parse("egypt")


def test_configs_point_at_different_files():
    ksa = load_region_config("ksa")
    pakistan = load_region_config("pakistan")
    assert ksa.database_path != pakistan.database_path
    assert ksa.seed_dir != pakistan.seed_dir
    assert ksa.currency == "SAR"
    assert pakistan.currency == "PKR"
    assert ksa.synthetic is True
    assert pakistan.synthetic is True


def test_records_do_not_cross_databases(regional_databases):
    ksa = RegionRepository("ksa", database_path=regional_databases["ksa"])
    pakistan = RegionRepository("pakistan", database_path=regional_databases["pakistan"])
    ksa_scope = ksa.load_scope()
    pakistan_scope = pakistan.load_scope()

    ksa_names = {row.name for row in ksa.list_suppliers(ksa_scope.supply_chain.id)}
    pakistan_names = {
        row.name for row in pakistan.list_suppliers(pakistan_scope.supply_chain.id)
    }
    assert "Malir Demo Mills" in pakistan_names
    assert "Malir Demo Mills" not in ksa_names
    assert "Oasis Gate Demo Foods" in ksa_names
    assert "Oasis Gate Demo Foods" not in pakistan_names

    ksa_ids = {row.id for row in ksa.list_suppliers(ksa_scope.supply_chain.id)}
    assert all(row_id.startswith("KSA-") for row_id in ksa_ids)
    assert all(
        row.id.startswith("PAK-")
        for row in pakistan.list_suppliers(pakistan_scope.supply_chain.id)
    )
    assert ksa_scope.supply_chain.id != pakistan_scope.supply_chain.id


def test_opening_the_other_regions_file_is_refused(regional_databases):
    mismatched = RegionRepository("ksa", database_path=regional_databases["pakistan"])
    with pytest.raises(ValueError, match="does not match the selected region"):
        mismatched.load_scope()
