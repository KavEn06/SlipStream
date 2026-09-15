from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("SLIPSTREAM_DATA_ROOT", str(REPO_ROOT / "data"))).expanduser()
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"
MODEL_ROOT = Path(os.getenv("SLIPSTREAM_MODEL_ROOT", str(DATA_ROOT / "models"))).expanduser()
CACHE_ROOT = Path(os.getenv("SLIPSTREAM_CACHE_ROOT", str(DATA_ROOT / "cache"))).expanduser()
IMPORT_CACHE_ROOT = CACHE_ROOT / "imports"

DEFAULT_LISTEN_IP = os.getenv("SLIPSTREAM_FORZA_IP", "127.0.0.1")
DEFAULT_LISTEN_PORT = int(os.getenv("SLIPSTREAM_FORZA_PORT", "5300"))
DEFAULT_SIM_NAME = "Forza Motorsport"
DEFAULT_RESAMPLE_POINTS = int(os.getenv("SLIPSTREAM_RESAMPLE_POINTS", "400"))
DEFAULT_SECTOR_BOUNDARIES = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
DEFAULT_IMPORT_BATCH_SIZE = int(os.getenv("SLIPSTREAM_IMPORT_BATCH_SIZE", "5000"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///{0}".format(DATA_ROOT / "slipstream.db"))


def _environment_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_root: Path
    model_root: Path
    cache_root: Path
    import_cache_root: Path
    import_batch_size: int
    experimental_detectors_enabled: bool = False


def get_settings() -> Settings:
    """Read runtime settings without requiring a dotenv dependency."""
    data_root = Path(os.getenv("SLIPSTREAM_DATA_ROOT", str(DATA_ROOT))).expanduser()
    model_root = Path(os.getenv("SLIPSTREAM_MODEL_ROOT", str(data_root / "models"))).expanduser()
    cache_root = Path(os.getenv("SLIPSTREAM_CACHE_ROOT", str(data_root / "cache"))).expanduser()
    database_url = os.getenv("DATABASE_URL", "sqlite:///{0}".format(data_root / "slipstream.db"))
    return Settings(
        database_url=database_url,
        data_root=data_root,
        model_root=model_root,
        cache_root=cache_root,
        import_cache_root=cache_root / "imports",
        import_batch_size=int(os.getenv("SLIPSTREAM_IMPORT_BATCH_SIZE", str(DEFAULT_IMPORT_BATCH_SIZE))),
        experimental_detectors_enabled=_environment_flag(
            "SLIPSTREAM_EXPERIMENTAL_DETECTORS"
        ),
    )


@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    raw_dir: Path
    processed_dir: Path
    raw_metadata_path: Path
    processed_metadata_path: Path


def build_session_id(now: Optional[datetime] = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}"


def get_session_paths(session_id: Optional[str] = None) -> SessionPaths:
    resolved_session_id = session_id or build_session_id()
    raw_dir = RAW_DATA_ROOT / resolved_session_id
    processed_dir = PROCESSED_DATA_ROOT / resolved_session_id

    return SessionPaths(
        session_id=resolved_session_id,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        raw_metadata_path=raw_dir / "metadata.json",
        processed_metadata_path=processed_dir / "metadata.json",
    )
