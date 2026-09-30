"""Find a region's config and open only that region's database file."""

import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

from domain.models import RegionCode


def project_root() -> Path:
    """The folder that contains rxconfig.py.

    persistence/ lives directly inside that folder, so the parent of this
    file's directory is the project root even if the command was started
    somewhere else.
    """
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RegionConfig:
    region_code: str
    display_name: str
    currency: str
    minor_unit_name: str
    timezone: str
    database_path: Path
    seed_dir: Path
    synthetic: bool


def load_region_config(region_code: str) -> RegionConfig:
    """Load regions/<code>/config.toml and reject anything that is not synthetic."""
    code = RegionCode.parse(region_code).value
    folder = project_root() / "regions" / code
    config_path = folder / "config.toml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing regional config: {config_path}")

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    if raw.get("region_code") != code:
        raise ValueError(
            f"{config_path} region_code must match the folder name '{code}'."
        )
    # A config that claims to be live data is refused. This MVP is synthetic only.
    if raw.get("synthetic") is not True:
        raise ValueError(f"{config_path} must set synthetic = true.")

    root = project_root()
    return RegionConfig(
        region_code=code,
        display_name=str(raw["display_name"]),
        currency=str(raw["currency"]),
        minor_unit_name=str(raw["minor_unit_name"]),
        timezone=str(raw["timezone"]),
        database_path=(root / str(raw["database_file"])).resolve(),
        seed_dir=(root / str(raw["seed_dir"])).resolve(),
        synthetic=True,
    )


def connect(database_path: Path) -> sqlite3.Connection:
    """Open one SQLite file with foreign keys enforced.

    The caller closes the connection. Keeping it short-lived avoids the
    file-lock trouble SQLite can hit on Windows when a second process
    tries to rebuild the same file.
    """
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
