from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

DEFAULT_LISTEN_IP = os.getenv("SLIPSTREAM_FORZA_IP", "127.0.0.1")
DEFAULT_LISTEN_PORT = int(os.getenv("SLIPSTREAM_FORZA_PORT", "5300"))
DEFAULT_SIM_NAME = "Forza Motorsport"
DEFAULT_RESAMPLE_POINTS = int(os.getenv("SLIPSTREAM_RESAMPLE_POINTS", "400"))
DEFAULT_SECTOR_BOUNDARIES = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)


@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    raw_dir: Path
    processed_dir: Path
    raw_metadata_path: Path
    processed_metadata_path: Path


def build_session_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}"


def get_session_paths(session_id: str | None = None) -> SessionPaths:
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
