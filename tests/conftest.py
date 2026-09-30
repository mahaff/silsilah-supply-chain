"""Shared fixtures. Databases are created in a temporary folder, not in data/."""

from pathlib import Path

import pytest

from persistence.seed import seed_region


@pytest.fixture
def regional_databases(tmp_path: Path) -> dict[str, Path]:
    return {
        region_code: seed_region(region_code, database_path=tmp_path / f"{region_code}.sqlite")
        for region_code in ("ksa", "pakistan")
    }
