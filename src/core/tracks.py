from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json


TRACKS_JSON_PATH = Path(__file__).resolve().parents[1] / "track_ordinals" / "tracks.json"


@lru_cache(maxsize=1)
def load_track_lookup() -> dict[int, dict[str, object]]:
    with TRACKS_JSON_PATH.open("r", encoding="utf-8") as handle:
        track_rows = json.load(handle)

    return {int(row["TrackOrdinal"]): row for row in track_rows}


def get_track_metadata(track_ordinal: int | None) -> dict[str, object]:
    if track_ordinal is None:
        return {}

    row = load_track_lookup().get(int(track_ordinal))
    if row is None:
        return {}

    return {
        "track_ordinal": int(row["TrackOrdinal"]),
        "track_circuit": row.get("Circuit"),
        "track_layout": row.get("Track"),
        "track_location": row.get("Location"),
        "track_length_m": float(row["Length_in_km"]) * 1000.0 if row.get("Length_in_km") is not None else None,
    }
