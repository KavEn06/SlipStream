"""Optional, guarded product inference for analyzed telemetry sessions.

The deterministic analysis layer remains authoritative.  This service adds
expected input bands and non-quantified recommendation ideas only when a
registered champion can be loaded and the current session is supported.
Every failure mode is converted to an explicit abstention result so normal
analysis never depends on a trained model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.core.config import get_settings
from src.db import models as database_models
from src.db.session import session_scope
from src.ml.dataset import PROFILE_TARGETS, LapDataset, TelemetryDatasetBuilder
from src.ml.registry import ModelRegistry
from src.ml.scenario import GuardedScenarioScorer, ScenarioModel


DEFAULT_GRID_POINTS = 64
DEFAULT_SECTION_COUNT = 8
DEFAULT_MINIMUM_SUPPORT = 0.35


@dataclass(frozen=True)
class MLInferenceResult:
    status: str
    model: Optional[Dict[str, Any]]
    dataset: Dict[str, Any]
    expected_profiles: Dict[str, Dict[str, Any]]
    section_pace: Dict[str, List[Dict[str, Any]]]
    recommendations: Tuple[Dict[str, Any], ...]
    support: Dict[str, Any]
    abstained: bool
    abstention_reasons: Tuple[str, ...]
    scenario: Dict[str, Any]
    conditions: Dict[str, Any]

    @classmethod
    def unavailable(
        cls,
        reason: str,
        dataset: Optional[Mapping[str, Any]] = None,
        model: Optional[Mapping[str, Any]] = None,
        conditions: Optional[Mapping[str, Any]] = None,
    ) -> "MLInferenceResult":
        return cls(
            status="unavailable",
            model=dict(model) if model is not None else None,
            dataset=dict(dataset or {}),
            expected_profiles={},
            section_pace={},
            recommendations=(),
            support={
                "minimum_required": DEFAULT_MINIMUM_SUPPORT,
                "overall": None,
                "by_section": {},
            },
            abstained=True,
            abstention_reasons=(reason,),
            scenario={"abstained": True, "abstention_reasons": [reason]},
            conditions=dict(conditions or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "optional": True,
            "model": dict(self.model) if self.model is not None else None,
            "dataset": dict(self.dataset),
            "expected_profiles": {
                str(key): dict(value)
                for key, value in self.expected_profiles.items()
            },
            "section_pace": {
                str(key): [dict(section) for section in sections]
                for key, sections in self.section_pace.items()
            },
            "recommendations": [dict(value) for value in self.recommendations],
            "support": dict(self.support),
            "abstained": self.abstained,
            "abstention_reasons": list(self.abstention_reasons),
            "scenario": dict(self.scenario),
            "conditions": dict(self.conditions),
            "authority": {
                "measured_time_loss": "authoritative",
                "lap_delta_reconciliation": "authoritative",
                "learned_output": "advisory",
                "seconds_saved_claimed": False,
            },
        }

    def context_for(
        self,
        lap_number: int,
        progress_norm: float,
    ) -> Optional[Dict[str, Any]]:
        sections = self.section_pace.get(str(lap_number), [])
        section = next(
            (
                item
                for item in sections
                if float(item["start_progress"]) <= progress_norm
                <= float(item["end_progress"])
            ),
            None,
        )
        if section is None:
            return None
        model = dict(self.model) if self.model is not None else None
        return {
            "learned": True,
            "model": model,
            "section_key": section["section_key"],
            "section_priority": section["priority"],
            "deviation_strength": section["deviation_strength"],
            "support": section["support"],
            "supported": section["supported"],
            "abstained": not bool(section["supported"]),
            "abstention_reason": section.get("abstention_reason"),
            "provenance": "registry_champion",
        }

    def profile_slice(
        self,
        lap_number: int,
        start_progress: float,
        end_progress: float,
    ) -> Optional[Dict[str, Any]]:
        profile = self.expected_profiles.get(str(lap_number))
        if profile is None:
            return None
        points = [
            point
            for point in profile.get("points", [])
            if start_progress <= float(point["progress_norm"]) <= end_progress
        ]
        if not points:
            return None
        return {
            "lap_number": lap_number,
            "model_version": (
                self.model.get("version") if self.model is not None else None
            ),
            "support": profile.get("support"),
            "points": points,
            "units": {
                "throttle": "fraction",
                "brake": "fraction",
                "steering": "normalized",
                "speed": "kph",
            },
        }

    def recommendation_for(self, progress_norm: float) -> Optional[Dict[str, Any]]:
        for recommendation in self.recommendations:
            start = recommendation.get("start_progress")
            end = recommendation.get("end_progress")
            if start is None or end is None:
                continue
            if float(start) <= progress_norm <= float(end):
                return dict(recommendation)
        return None


class MLProductInferenceService:
    """Load a champion and produce guarded, current-session product output."""

    def __init__(
        self,
        database_factory: Any = None,
        model_root: Optional[Path] = None,
        minimum_support: float = DEFAULT_MINIMUM_SUPPORT,
    ):
        self.database_factory = database_factory
        self.model_root = Path(model_root or get_settings().model_root)
        self.minimum_support = float(minimum_support)

    def infer(
        self,
        session_id: str,
        laps: Mapping[int, pd.DataFrame],
        session_metadata: Optional[Mapping[str, Any]] = None,
        conditions: Optional[Mapping[str, Any]] = None,
    ) -> MLInferenceResult:
        metadata = dict(session_metadata or {})
        resolved_conditions = self._conditions(metadata, conditions)
        loaded = self._load_champion()
        if loaded[0] is None:
            return MLInferenceResult.unavailable(
                loaded[2] or "no_registered_champion",
                conditions=resolved_conditions,
            )

        model, model_context, _ = loaded
        if not hasattr(model, "predict_profiles") or not (
            hasattr(model, "predict_section_pace")
            or hasattr(model, "predict_scenario")
        ):
            return MLInferenceResult.unavailable(
                "incompatible_model_interface",
                model=model_context,
                conditions=resolved_conditions,
            )
        grid_points = self._positive_int(
            model_context.get("grid_points"), DEFAULT_GRID_POINTS
        )
        section_count = self._positive_int(
            model_context.get("section_count"), DEFAULT_SECTION_COUNT
        )
        if grid_points < 8 or section_count < 2 or section_count > grid_points // 2:
            return MLInferenceResult.unavailable(
                "incompatible_model_dimensions",
                model=model_context,
                conditions=resolved_conditions,
            )

        try:
            dataset = self._build_dataset(
                session_id,
                laps,
                metadata,
                resolved_conditions,
                grid_points,
                section_count,
            )
        except (TypeError, ValueError):
            return MLInferenceResult.unavailable(
                "current_session_dataset_unavailable",
                model=model_context,
                conditions=resolved_conditions,
            )

        dataset_context = {
            "normalized": True,
            "grid_points": dataset.grid_points,
            "section_count": dataset.section_count,
            "sample_rows": dataset.sample_row_count,
            "effective_laps": dataset.effective_lap_count,
            "session_only": True,
        }
        if (
            getattr(model, "grid_points", grid_points) not in (None, grid_points)
            or getattr(model, "section_count", section_count)
            not in (None, section_count)
        ):
            return MLInferenceResult.unavailable(
                "incompatible_model_dimensions",
                dataset=dataset_context,
                model=model_context,
                conditions=resolved_conditions,
            )

        try:
            support_values = self._support(model, dataset.section_frame)
            ood_reasons = self._ood_reasons(model, resolved_conditions)
            profile_prediction = self._profile_prediction(model, dataset)
            section_prediction = self._section_prediction(model, dataset)
        except Exception as exc:
            return MLInferenceResult.unavailable(
                "inference_failed:{0}".format(type(exc).__name__),
                dataset=dataset_context,
                model=model_context,
                conditions=resolved_conditions,
            )

        section_pace = self._section_pace(
            dataset, section_prediction, support_values, ood_reasons
        )
        expected_profiles = self._expected_profiles(
            dataset, profile_prediction, support_values, ood_reasons
        )
        support_by_section = {
            "{0}:{1}".format(
                int(row.get("lap_number", 0)), str(row["section_key"])
            ): _finite_float(support)
            for (_, row), support in zip(dataset.section_frame.iterrows(), support_values)
        }
        finite_support = [
            float(value) for value in support_values if np.isfinite(value)
        ]
        overall_support = (
            float(np.mean(finite_support)) if finite_support else None
        )

        scenario_models = self._load_scenario_models(model, model_context)
        scenario_payload, recommendations = self._scenario(
            scenario_models,
            dataset,
            resolved_conditions,
        )
        reasons = list(ood_reasons)
        if not expected_profiles:
            if finite_support and min(finite_support) < self.minimum_support:
                reasons.append("insufficient_nearby_support")
            elif not finite_support:
                reasons.append("support_unavailable")
        reasons = sorted(set(reasons))
        return MLInferenceResult(
            status="available" if expected_profiles else "abstained",
            model=model_context,
            dataset=dataset_context,
            expected_profiles=expected_profiles,
            section_pace=section_pace,
            recommendations=tuple(recommendations),
            support={
                "minimum_required": self.minimum_support,
                "overall": overall_support,
                "by_section": support_by_section,
            },
            abstained=not bool(expected_profiles),
            abstention_reasons=tuple(reasons),
            scenario=scenario_payload,
            conditions=resolved_conditions,
        )

    def _load_champion(
        self,
    ) -> Tuple[Optional[Any], Dict[str, Any], Optional[str]]:
        if self.database_factory is None:
            return None, {}, "model_registry_unavailable"
        try:
            with session_scope(self.database_factory) as database_session:
                registry = ModelRegistry(database_session, self.model_root)
                row = registry.champion_row()
                if row is None:
                    return None, {}, "no_registered_champion"
                compatibility = dict(row.compatibility or {})
                dataset_metadata = dict(row.metadata_json or {}).get("dataset")
                model_context = {
                    "id": int(row.id),
                    "name": str(row.name),
                    "version": str(row.version),
                    "family": str(row.model_type),
                    "status": str(row.status),
                    "grid_points": compatibility.get("grid_points")
                    or dict(row.metadata_json or {}).get("grid_points"),
                    "section_count": compatibility.get("section_count")
                    or dict(row.metadata_json or {}).get("section_count"),
                    "source_revisions": dict(row.source_revisions or {}),
                    "provenance": "checksummed_registry_champion",
                    "dataset_fingerprint": (
                        dataset_metadata.get("fingerprint")
                        if isinstance(dataset_metadata, dict)
                        else None
                    ),
                }
                if not (
                    str(row.model_type).startswith("sklearn")
                    or str(row.model_type).startswith("torch")
                ):
                    return None, model_context, "incompatible_model_family"
                model = registry.load_champion()
                return model, model_context, None
        except LookupError:
            return None, {}, "no_registered_champion"
        except Exception as exc:
            return None, {}, "champion_load_failed:{0}".format(type(exc).__name__)

    def _load_scenario_models(
        self,
        champion: Any,
        champion_context: Mapping[str, Any],
    ) -> List[ScenarioModel]:
        """Load one checksum-verified model per compatible family.

        Expected-profile rendering remains champion-only. Scenario ideas use a
        same-dataset challenger from another family when available so the
        scorer can enforce cross-family agreement.
        """

        configured = [
            ScenarioModel(
                str(champion_context.get("family") or "unknown"),
                str(champion_context.get("version") or "unknown"),
                champion,
            )
        ]
        if self.database_factory is None:
            return configured

        champion_family = _model_family(champion_context.get("family"))
        fingerprint = champion_context.get("dataset_fingerprint")
        seen_families = {champion_family}
        try:
            with session_scope(self.database_factory) as database_session:
                registry = ModelRegistry(database_session, self.model_root)
                rows = list(
                    database_session.scalars(
                        select(database_models.ModelVersion)
                        .where(
                            database_models.ModelVersion.name
                            == champion_context.get("name"),
                            database_models.ModelVersion.id
                            != champion_context.get("id"),
                        )
                        .order_by(
                            database_models.ModelVersion.created_at.desc(),
                            database_models.ModelVersion.id.desc(),
                        )
                    ).all()
                )
                for row in rows:
                    family = _model_family(row.model_type)
                    if family in seen_families or family == "unknown":
                        continue
                    compatibility = dict(row.compatibility or {})
                    if (
                        compatibility.get("grid_points")
                        != champion_context.get("grid_points")
                        or compatibility.get("section_count")
                        != champion_context.get("section_count")
                    ):
                        continue
                    row_dataset = dict(row.metadata_json or {}).get("dataset")
                    row_fingerprint = (
                        row_dataset.get("fingerprint")
                        if isinstance(row_dataset, dict)
                        else None
                    )
                    if fingerprint is not None and row_fingerprint != fingerprint:
                        continue
                    try:
                        model = registry.load_version(row)
                    except Exception:
                        continue
                    if not hasattr(model, "support_score") or not (
                        hasattr(model, "predict_section_pace")
                        or hasattr(model, "predict_scenario")
                    ):
                        continue
                    configured.append(
                        ScenarioModel(str(row.model_type), str(row.version), model)
                    )
                    seen_families.add(family)
        except Exception:
            return configured
        return configured

    @staticmethod
    def _build_dataset(
        session_id: str,
        laps: Mapping[int, pd.DataFrame],
        metadata: Mapping[str, Any],
        conditions: Mapping[str, Any],
        grid_points: int,
        section_count: int,
    ) -> LapDataset:
        frames: Dict[str, pd.DataFrame] = {}
        per_lap_metadata: Dict[str, Dict[str, Any]] = {}
        track_key = "{0}:{1}".format(
            metadata.get("track_circuit")
            or metadata.get("track_ordinal")
            or "unknown-track",
            metadata.get("track_layout") or "default",
        )
        car_key = str(
            metadata.get("car_identity")
            or metadata.get("car_ordinal")
            or "unknown-car"
        )
        for lap_number, frame in laps.items():
            key = "{0}:lap-{1}".format(session_id, int(lap_number))
            frames[key] = frame
            per_lap_metadata[key] = {
                "session_key": session_id,
                "lap_number": int(lap_number),
                "lap_time_s": _frame_number(frame, "LapTimeS"),
                "is_valid": True,
                "simulator": metadata.get("sim") or "unknown-simulator",
                "track_key": track_key,
                "car_key": car_key,
                "track_length_m": metadata.get("track_length_m"),
                "conditions": dict(conditions),
                "source_key": "current-session-analysis",
            }
        return TelemetryDatasetBuilder(
            grid_points=grid_points,
            section_count=section_count,
            valid_only=True,
        ).from_processed_laps(frames, metadata=per_lap_metadata)

    @staticmethod
    def _profile_prediction(model: Any, dataset: LapDataset) -> Any:
        try:
            return model.predict_profiles(
                dataset.sample_frame, dataset.section_frame
            )
        except TypeError:
            return model.predict_profiles(dataset.sample_frame)

    @staticmethod
    def _section_prediction(model: Any, dataset: LapDataset) -> Any:
        if hasattr(model, "predict_section_pace"):
            return model.predict_section_pace(dataset.section_frame)
        if hasattr(model, "predict_scenario"):
            section, _ = model.predict_scenario(
                dataset.sample_frame, dataset.section_frame
            )
            return section
        raise TypeError("Champion model does not support section pace inference")

    @staticmethod
    def _support(model: Any, section_frame: pd.DataFrame) -> np.ndarray:
        method = getattr(model, "support_score", None)
        if method is None:
            return np.full(len(section_frame), np.nan, dtype=float)
        values = np.asarray(method(section_frame), dtype=float).reshape(-1)
        if len(values) != len(section_frame):
            raise ValueError("Champion returned an invalid support shape")
        return np.clip(values, 0.0, 1.0)

    @staticmethod
    def _ood_reasons(
        model: Any, conditions: Mapping[str, Any]
    ) -> List[str]:
        method = getattr(model, "condition_ood_reasons", None)
        if method is None:
            return []
        return sorted(set(str(reason) for reason in method(conditions)))

    def _expected_profiles(
        self,
        dataset: LapDataset,
        prediction: Any,
        support_values: np.ndarray,
        ood_reasons: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        expected = np.asarray(prediction.expected, dtype=float)
        lower = np.asarray(prediction.lower, dtype=float)
        upper = np.asarray(prediction.upper, dtype=float)
        if (
            expected.shape != (len(dataset.sample_frame), len(PROFILE_TARGETS))
            or lower.shape != expected.shape
            or upper.shape != expected.shape
        ):
            raise ValueError("Champion returned an invalid profile shape")
        sample = dataset.sample_frame.reset_index(drop=True)
        sections = dataset.section_frame.reset_index(drop=True)
        result: Dict[str, Dict[str, Any]] = {}
        offset = 0
        section_offset = 0
        for _, lap in dataset.lap_frame.iterrows():
            lap_key = str(lap["lap_key"])
            lap_number = int(lap.get("lap_number", 0))
            rows = sample[sample["lap_key"].astype(str) == lap_key]
            count = len(rows)
            lap_sections = sections[sections["lap_key"].astype(str) == lap_key]
            section_support = support_values[
                section_offset : section_offset + len(lap_sections)
            ]
            section_offset += len(lap_sections)
            support = (
                float(np.min(section_support))
                if len(section_support) and np.isfinite(section_support).all()
                else None
            )
            supported = (
                not ood_reasons
                and support is not None
                and support >= self.minimum_support
            )
            if not supported:
                offset += count
                continue
            points = []
            for local_index, (_, row) in enumerate(rows.iterrows()):
                index = offset + local_index
                points.append(
                    {
                        "progress_norm": _finite_float(row["progress"]),
                        "throttle": _band(expected, lower, upper, index, 0, 1.0),
                        "brake": _band(expected, lower, upper, index, 1, 1.0),
                        "steering": _band(expected, lower, upper, index, 2, 1.0),
                        "speed": _band(expected, lower, upper, index, 3, 3.6),
                    }
                )
            offset += count
            result[str(lap_number)] = {
                "lap_number": lap_number,
                "support": support,
                "points": points,
            }
        return result

    def _section_pace(
        self,
        dataset: LapDataset,
        prediction: Any,
        support_values: np.ndarray,
        ood_reasons: Sequence[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        expected = np.asarray(prediction.expected, dtype=float).reshape(-1)
        lower = np.asarray(prediction.lower, dtype=float).reshape(-1)
        upper = np.asarray(prediction.upper, dtype=float).reshape(-1)
        if not (
            len(expected)
            == len(lower)
            == len(upper)
            == len(dataset.section_frame)
        ):
            raise ValueError("Champion returned an invalid section pace shape")
        result: Dict[str, List[Dict[str, Any]]] = {}
        for index, (_, row) in enumerate(
            dataset.section_frame.reset_index(drop=True).iterrows()
        ):
            support = _finite_float(support_values[index])
            supported = (
                not ood_reasons
                and support is not None
                and support >= self.minimum_support
            )
            width = max(float(upper[index] - lower[index]), 1e-4)
            observed = float(row["section_time_s"])
            deviation = max((observed - float(upper[index])) / width, 0.0)
            deviation_strength = float(np.clip(deviation, 0.0, 1.0))
            priority = float(
                np.clip(
                    0.65 * deviation_strength
                    + 0.35 * (support if support is not None else 0.0),
                    0.0,
                    1.0,
                )
            )
            lap_number = int(row.get("lap_number", 0))
            result.setdefault(str(lap_number), []).append(
                {
                    "section_key": str(row["section_key"]),
                    "section_index": int(row["section_index"]),
                    "start_progress": _finite_float(row["start_progress"]),
                    "end_progress": _finite_float(row["end_progress"]),
                    "observed_time_s": _finite_float(observed),
                    "expected_time_s": (
                        _finite_float(expected[index]) if supported else None
                    ),
                    "lower_time_s": (
                        _finite_float(lower[index]) if supported else None
                    ),
                    "upper_time_s": (
                        _finite_float(upper[index]) if supported else None
                    ),
                    "support": support,
                    "supported": supported,
                    "abstention_reason": (
                        ", ".join(ood_reasons)
                        if ood_reasons
                        else (
                            "insufficient_nearby_support"
                            if not supported
                            else None
                        )
                    ),
                    "deviation_strength": deviation_strength if supported else None,
                    "priority": priority if supported else None,
                    "pace_is_advisory": True,
                }
            )
        return result

    def _scenario(
        self,
        scenario_models: Sequence[ScenarioModel],
        dataset: LapDataset,
        conditions: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        model = scenario_models[0].model
        if not hasattr(model, "support_score"):
            return {
                "abstained": True,
                "abstention_reasons": ["support_unavailable"],
            }, []
        lap_key = str(
            dataset.lap_frame.sort_values("lap_time_s").iloc[0]["lap_key"]
        )
        samples = dataset.sample_frame[
            dataset.sample_frame["lap_key"].astype(str) == lap_key
        ].copy()
        sections = dataset.section_frame[
            dataset.section_frame["lap_key"].astype(str) == lap_key
        ].copy()
        try:
            result = GuardedScenarioScorer(
                scenario_models,
                minimum_support=self.minimum_support,
            ).score(samples, sections, conditions=conditions, lap_key=lap_key)
        except Exception as exc:
            reason = "scenario_inference_failed:{0}".format(type(exc).__name__)
            return {
                "abstained": True,
                "abstention_reasons": [reason],
            }, []

        by_key = {
            str(row["section_key"]): row for _, row in sections.iterrows()
        }
        recommendations: List[Dict[str, Any]] = []
        for recommendation in result.recommendations:
            payload = asdict(recommendation)
            section = by_key.get(str(recommendation.section_key))
            payload["model_version"] = scenario_models[0].version
            payload["model_family"] = scenario_models[0].family
            payload["conditions"] = dict(conditions)
            payload["non_quantified_idea"] = True
            payload["seconds_saved_claimed"] = False
            if section is not None:
                payload["start_progress"] = _finite_float(
                    section["start_progress"]
                )
                payload["end_progress"] = _finite_float(section["end_progress"])
            recommendations.append(payload)
        if not recommendations and not result.abstained:
            reasons = ["no_guarded_scenario_improvement"]
        else:
            reasons = list(result.abstention_reasons)
        return {
            "abstained": result.abstained or not bool(recommendations),
            "abstention_reasons": reasons,
            "assessments_considered": len(result.assessments),
            "recommendation_count": len(recommendations),
            "models_consulted": [
                {"family": configured.family, "version": configured.version}
                for configured in scenario_models
            ],
        }, recommendations

    @staticmethod
    def _conditions(
        metadata: Mapping[str, Any],
        override: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        result = (
            dict(metadata.get("conditions") or {})
            if isinstance(metadata.get("conditions"), Mapping)
            else {}
        )
        result.update(dict(override or {}))
        return {
            key: value
            for key, value in result.items()
            if value is not None and _is_finite_or_text(value)
        }

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            resolved = int(value)
            return resolved if resolved > 0 else default
        except (TypeError, ValueError):
            return default


def _frame_number(frame: pd.DataFrame, column: str) -> Optional[float]:
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _band(
    expected: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    row: int,
    column: int,
    scale: float,
) -> Dict[str, Optional[float]]:
    return {
        "expected": _finite_float(expected[row, column] * scale),
        "lower": _finite_float(lower[row, column] * scale),
        "upper": _finite_float(upper[row, column] * scale),
    }


def _finite_float(value: Any) -> Optional[float]:
    try:
        resolved = float(value)
        return resolved if math.isfinite(resolved) else None
    except (TypeError, ValueError):
        return None


def _is_finite_or_text(value: Any) -> bool:
    if isinstance(value, (str, bool)):
        return True
    return _finite_float(value) is not None


def _model_family(value: Any) -> str:
    normalized = str(value or "").lower()
    if normalized.startswith("sklearn"):
        return "sklearn"
    if normalized.startswith("torch"):
        return "torch"
    return "unknown"


def fallback_recommendation_id(
    session_id: str,
    reasons: Sequence[str],
) -> str:
    """Stable helper reserved for future deterministic fallback persistence."""
    encoded = json.dumps(
        {"session_id": session_id, "reasons": sorted(reasons)},
        sort_keys=True,
    ).encode("utf-8")
    return "rec_{0}".format(hashlib.sha256(encoded).hexdigest()[:24])
