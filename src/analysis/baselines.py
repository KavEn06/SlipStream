"""Per-corner baselines for the analysis layer.

The v1 baseline strategy is **per-corner fastest-time reference**: for every
``corner_id`` we pick the ``(lap, CornerRecord)`` with the smallest
``corner_time_s`` (excluding records with fallback alignment inside the
corner). This is distinct from — and usually more informative than — the
session-wide fastest lap's version of the corner, because different laps
can win different corners.

Nothing in this module reads files or calls segmentation. It is a pure
argmin over a collection of already-built ``CornerRecord`` instances.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from src.analysis.corner_records import CornerRecord


@dataclass(frozen=True)
class CornerBaseline:
    """Fastest-time reference for a single corner across usable laps."""

    corner_id: int
    reference_lap_number: int
    reference_record: CornerRecord
    candidate_lap_numbers: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "reference_lap_number": self.reference_lap_number,
            "reference_record": self.reference_record.to_dict(),
            "candidate_lap_numbers": list(self.candidate_lap_numbers),
        }


def build_per_corner_baselines(
    records_by_corner: dict[int, list[CornerRecord]],
) -> dict[int, CornerBaseline]:
    """Pick the fastest-through-corner reference per corner.

    Parameters
    ----------
    records_by_corner:
        ``{corner_id: [CornerRecord, ...]}`` grouped across laps.

    Returns
    -------
    ``{corner_id: CornerBaseline}`` containing one baseline per corner that
    has at least one usable record. Corners with zero usable records (every
    lap tripped the alignment-fallback gate) are omitted from the result —
    detectors will have nothing to compare against for those corners, which
    is the correct behavior.
    """
    baselines: dict[int, CornerBaseline] = {}
    for corner_id, records in records_by_corner.items():
        baseline = _select_baseline(corner_id, records)
        if baseline is not None:
            baselines[corner_id] = baseline
    return baselines


def group_records_by_corner(
    records: Iterable[CornerRecord],
) -> dict[int, list[CornerRecord]]:
    """Bucket a flat list of corner records by ``corner_id``.

    Preserves input order within each bucket, which matters for the
    tie-breaking behavior of :func:`build_per_corner_baselines`.
    """
    grouped: dict[int, list[CornerRecord]] = {}
    for record in records:
        grouped.setdefault(record.corner_id, []).append(record)
    return grouped


def _select_baseline(
    corner_id: int, records: list[CornerRecord]
) -> CornerBaseline | None:
    usable = [r for r in records if _is_usable(r)]
    if not usable:
        return None

    # Sort by (corner_time_s, lap_number) so ties resolve to the earliest lap.
    usable_sorted = sorted(usable, key=lambda r: (r.corner_time_s, r.lap_number))
    best = usable_sorted[0]

    candidate_lap_numbers = sorted({r.lap_number for r in records})
    return CornerBaseline(
        corner_id=corner_id,
        reference_lap_number=best.lap_number,
        reference_record=best,
        candidate_lap_numbers=candidate_lap_numbers,
    )


def _is_usable(record: CornerRecord) -> bool:
    """A record is usable as a baseline iff it has trustworthy alignment.

    We never pick a record that tripped the fallback path inside its corner
    window — the time delta computed against it would be measuring alignment
    noise, not driving.
    """
    if record.alignment_used_fallback:
        return False
    if record.corner_time_s <= 0.0:
        return False
    return True
