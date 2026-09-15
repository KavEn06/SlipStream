"""Guarded observational scenario analysis for driver-actionable ideas."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.ml.dataset import ACTIONABLE_FEATURES


PERTURBATION_CAPS = {
    "brake_onset": 0.035,
    "min_speed_ratio": 0.040,
    "throttle_pickup": 0.035,
    "coasting_fraction": 0.060,
    "steering_instability": 0.020,
}
PERTURBATION_DIRECTIONS = {
    "brake_onset": -1.0,
    "min_speed_ratio": 1.0,
    "throttle_pickup": -1.0,
    "coasting_fraction": -1.0,
    "steering_instability": -1.0,
}
CUES = {
    "brake_onset": "Begin braking slightly earlier and build pressure progressively.",
    "min_speed_ratio": "Release braking smoothly and preserve a little more minimum speed.",
    "throttle_pickup": "Prioritise a settled car, then begin throttle pickup slightly earlier.",
    "coasting_fraction": "Reduce the neutral coast phase with a deliberate brake-to-throttle transition.",
    "steering_instability": "Use one calmer steering input and unwind it progressively on exit.",
}
HYPOTHESES = {
    "brake_onset": "A small earlier, progressive brake initiation is associated with stronger complete laps.",
    "min_speed_ratio": "A modest increase in supported minimum speed is associated with stronger complete laps.",
    "throttle_pickup": "A small earlier throttle pickup after rotation is associated with stronger complete laps.",
    "coasting_fraction": "A shorter coast phase is associated with stronger complete laps.",
    "steering_instability": "Lower steering correction activity is associated with stronger complete laps.",
}


@dataclass(frozen=True)
class ScenarioModel:
    family: str
    version: str
    model: Any


@dataclass(frozen=True)
class CandidateAssessment:
    section_key: str
    feature: str
    baseline_value: float
    proposed_value: float
    section_delta_s: float
    whole_lap_delta_s: float
    support: float
    disagreement: float
    relative_uncertainty: float
    accepted: bool
    rejection_reason: Optional[str]


@dataclass(frozen=True)
class RecommendationIdea:
    recommendation_id: str
    section_key: str
    feature: str
    hypothesis: str
    cue: str
    learned: bool
    confidence: float
    driver_baseline: Mapping[str, Any]
    perturbation: Mapping[str, float]
    provenance: Mapping[str, Any]
    abstention_reason: Optional[str] = None


@dataclass(frozen=True)
class ScenarioResult:
    recommendations: Tuple[RecommendationIdea, ...]
    assessments: Tuple[CandidateAssessment, ...]
    abstained: bool
    abstention_reasons: Tuple[str, ...]


class GuardedScenarioScorer:
    """Score bounded scenarios and veto unsupported or whole-lap regressions."""

    def __init__(
        self,
        models: Sequence[ScenarioModel],
        minimum_support: float = 0.35,
        maximum_disagreement: float = 0.75,
        maximum_relative_uncertainty: float = 0.35,
        lap_regression_tolerance_fraction: float = 0.0,
        max_recommendations: int = 3,
    ):
        if not models:
            raise ValueError("At least one fitted model family is required")
        self.models = tuple(models)
        self.minimum_support = float(minimum_support)
        self.maximum_disagreement = float(maximum_disagreement)
        self.maximum_relative_uncertainty = float(maximum_relative_uncertainty)
        self.lap_regression_tolerance_fraction = float(
            lap_regression_tolerance_fraction
        )
        self.max_recommendations = int(max_recommendations)

    def score(
        self,
        sample_frame: pd.DataFrame,
        section_frame: pd.DataFrame,
        conditions: Optional[Mapping[str, Any]] = None,
        lap_key: Optional[str] = None,
    ) -> ScenarioResult:
        if section_frame.empty:
            raise ValueError("section_frame cannot be empty")
        section_frame = section_frame.sort_values("section_index").reset_index(drop=True)
        conditions = dict(conditions or {})
        ood_reasons = self._condition_ood_reasons(conditions)
        if ood_reasons:
            fallback = self._fallback(
                section_frame,
                conditions,
                ood_reasons,
                lap_key=lap_key,
            )
            return ScenarioResult(
                recommendations=(fallback,),
                assessments=(),
                abstained=True,
                abstention_reasons=tuple(ood_reasons),
            )

        baseline_scores = [
            self._score_family(model, sample_frame, section_frame)
            for model in self.models
        ]
        assessments: List[CandidateAssessment] = []
        accepted_by_section: Dict[str, List[Tuple[CandidateAssessment, RecommendationIdea]]] = {}
        for row_index, (_, section) in enumerate(section_frame.iterrows()):
            section_key = str(section.get("section_key", "s{0:02d}".format(row_index)))
            for feature, proposed_value in self._candidate_values(section).items():
                changed = section_frame.copy()
                changed_index = changed.index[
                    changed["section_key"].astype(str) == section_key
                ]
                if len(changed_index) != 1:
                    continue
                changed.loc[changed_index[0], feature] = proposed_value
                candidate_scores = [
                    self._score_family(model, sample_frame, changed)
                    for model in self.models
                ]
                section_deltas = np.asarray(
                    [
                        candidate["section_expected"][row_index]
                        - baseline["section_expected"][row_index]
                        for baseline, candidate in zip(
                            baseline_scores, candidate_scores
                        )
                    ],
                    dtype=float,
                )
                lap_deltas = np.asarray(
                    [
                        candidate["lap_expected"][0] - baseline["lap_expected"][0]
                        for baseline, candidate in zip(
                            baseline_scores, candidate_scores
                        )
                    ],
                    dtype=float,
                )
                support = float(
                    min(
                        candidate["support"][row_index]
                        for candidate in candidate_scores
                    )
                )
                disagreement = self._disagreement(section_deltas, lap_deltas)
                relative_uncertainty = self._relative_uncertainty(
                    row_index, baseline_scores, candidate_scores
                )
                baseline_lap = max(
                    float(np.mean([score["lap_expected"][0] for score in baseline_scores])),
                    1e-6,
                )
                tolerance = baseline_lap * self.lap_regression_tolerance_fraction
                rejection = self._rejection_reason(
                    section_deltas,
                    lap_deltas,
                    support,
                    disagreement,
                    relative_uncertainty,
                    tolerance,
                )
                assessment = CandidateAssessment(
                    section_key=section_key,
                    feature=feature,
                    baseline_value=float(section[feature]),
                    proposed_value=float(proposed_value),
                    section_delta_s=float(np.mean(section_deltas)),
                    whole_lap_delta_s=float(np.mean(lap_deltas)),
                    support=support,
                    disagreement=disagreement,
                    relative_uncertainty=relative_uncertainty,
                    accepted=rejection is None,
                    rejection_reason=rejection,
                )
                assessments.append(assessment)
                if rejection is None:
                    confidence = self._confidence(
                        support,
                        disagreement,
                        relative_uncertainty,
                        section_deltas,
                        lap_deltas,
                    )
                    recommendation = self._learned_recommendation(
                        assessment,
                        section,
                        confidence,
                        lap_key=lap_key,
                    )
                    accepted_by_section.setdefault(section_key, []).append(
                        (assessment, recommendation)
                    )

        recommendations = []
        for values in accepted_by_section.values():
            _, recommendation = min(
                values,
                key=lambda value: (
                    value[0].whole_lap_delta_s,
                    value[0].section_delta_s,
                    value[0].feature,
                ),
            )
            recommendations.append(recommendation)
        recommendations.sort(
            key=lambda idea: (
                -idea.confidence,
                idea.section_key,
                idea.feature,
            )
        )
        recommendations = recommendations[: self.max_recommendations]
        rejection_reasons = {
            assessment.rejection_reason
            for assessment in assessments
            if assessment.rejection_reason is not None
        }
        support_abstention = bool(assessments) and rejection_reasons.issubset(
            {
                "insufficient_nearby_support",
                "invalid_support",
                "ensemble_disagreement",
                "excessive_predictive_uncertainty",
            }
        )
        if not recommendations and support_abstention:
            reasons = tuple(sorted(str(reason) for reason in rejection_reasons))
            fallback = self._fallback(
                section_frame,
                conditions,
                reasons,
                lap_key=lap_key,
            )
            return ScenarioResult(
                recommendations=(fallback,),
                assessments=tuple(assessments),
                abstained=True,
                abstention_reasons=reasons,
            )
        return ScenarioResult(
            recommendations=tuple(recommendations),
            assessments=tuple(assessments),
            abstained=False,
            abstention_reasons=(),
        )

    def _candidate_values(self, section: pd.Series) -> Dict[str, float]:
        consistency = max(float(section.get("driver_consistency", 0.0)), 0.0)
        progressive_scale = float(np.clip(1.0 - 8.0 * consistency, 0.25, 1.0))
        bounds = self._comparable_bounds(section)
        values: Dict[str, float] = {}
        for feature in ACTIONABLE_FEATURES:
            baseline = float(section[feature])
            cap = PERTURBATION_CAPS[feature] * progressive_scale
            proposed = baseline + PERTURBATION_DIRECTIONS[feature] * cap
            low, high = bounds.get(feature, self._physical_bounds(feature))
            physical_low, physical_high = self._physical_bounds(feature)
            proposed = float(
                np.clip(proposed, max(low, physical_low), min(high, physical_high))
            )
            if abs(proposed - baseline) >= max(cap * 0.15, 1e-5):
                values[feature] = proposed
        return values

    def _comparable_bounds(self, section: pd.Series) -> Dict[str, Tuple[float, float]]:
        all_bounds: List[Mapping[str, Tuple[float, float]]] = []
        for configured in self.models:
            method = getattr(configured.model, "feature_bounds", None)
            if method is not None:
                all_bounds.append(
                    method(str(section.get("track_key")), str(section.get("car_key")))
                )
        combined: Dict[str, Tuple[float, float]] = {}
        for feature in ACTIONABLE_FEATURES:
            lows = [
                float(bounds[feature][0])
                for bounds in all_bounds
                if feature in bounds and np.isfinite(bounds[feature][0])
            ]
            highs = [
                float(bounds[feature][1])
                for bounds in all_bounds
                if feature in bounds and np.isfinite(bounds[feature][1])
            ]
            if lows and highs:
                low = max(lows)
                high = min(highs)
                if low <= high:
                    combined[feature] = (low, high)
        return combined

    @staticmethod
    def _physical_bounds(feature: str) -> Tuple[float, float]:
        if feature == "steering_instability":
            return 0.0, 1.0
        return 0.0, 1.0

    def _score_family(
        self,
        configured: ScenarioModel,
        sample_frame: pd.DataFrame,
        section_frame: pd.DataFrame,
    ) -> Dict[str, np.ndarray]:
        model = configured.model
        if hasattr(model, "predict_scenario"):
            section_prediction, lap_prediction = model.predict_scenario(
                sample_frame, section_frame
            )
        else:
            section_prediction = model.predict_section_pace(section_frame)
            lap_prediction = model.predict_lap_pace(section_frame)
        support_method = getattr(model, "support_score", None)
        support = (
            np.asarray(support_method(section_frame), dtype=float)
            if support_method is not None
            else np.ones(len(section_frame), dtype=float)
        )
        return {
            "section_expected": np.asarray(
                section_prediction.expected, dtype=float
            ).reshape(-1),
            "section_lower": np.asarray(
                section_prediction.lower, dtype=float
            ).reshape(-1),
            "section_upper": np.asarray(
                section_prediction.upper, dtype=float
            ).reshape(-1),
            "lap_expected": np.asarray(lap_prediction.expected, dtype=float).reshape(-1),
            "lap_lower": np.asarray(lap_prediction.lower, dtype=float).reshape(-1),
            "lap_upper": np.asarray(lap_prediction.upper, dtype=float).reshape(-1),
            "support": support,
        }

    def _condition_ood_reasons(self, conditions: Mapping[str, Any]) -> List[str]:
        reasons: List[str] = []
        normalized = {
            "wetness": conditions.get(
                "wetness", conditions.get("track_wetness", conditions.get("rain"))
            ),
            "air_temp_c": conditions.get("air_temp_c"),
            "track_temp_c": conditions.get("track_temp_c"),
            "tyre_wear": conditions.get(
                "tyre_wear", conditions.get("tire_wear")
            ),
        }
        wetness = self._float_or_none(normalized["wetness"])
        tyre_wear = self._float_or_none(normalized["tyre_wear"])
        track_temp = self._float_or_none(normalized["track_temp_c"])
        if wetness is not None and wetness >= 0.10:
            reasons.append("wet_conditions")
        if tyre_wear is not None and tyre_wear >= 0.70:
            reasons.append("high_tyre_wear")
        if track_temp is not None and track_temp <= 8.0:
            reasons.append("cold_track")
        for configured in self.models:
            method = getattr(configured.model, "condition_ood_reasons", None)
            if method is not None:
                reasons.extend(str(reason) for reason in method(normalized))
        return sorted(set(reasons))

    def _fallback(
        self,
        section_frame: pd.DataFrame,
        conditions: Mapping[str, Any],
        reasons: Sequence[str],
        lap_key: Optional[str],
    ) -> RecommendationIdea:
        first = section_frame.sort_values("section_index").iloc[0]
        if "wet_conditions" in reasons:
            cue = (
                "Use earlier progressive braking, smooth steering, and traction-first exits; "
                "adapt the line to available grip."
            )
        elif "cold_track" in reasons:
            cue = (
                "Build pace progressively with earlier braking and smooth inputs until grip is established."
            )
        elif "high_tyre_wear" in reasons:
            cue = (
                "Protect the tyre with progressive braking, calm steering, and measured throttle exits."
            )
        else:
            cue = (
                "Build pace progressively and prioritise smooth, repeatable brake-to-throttle transitions."
            )
        provenance = {
            "schema_version": "1.0",
            "kind": "deterministic-conservative-fallback",
            "models_consulted": [
                {"family": model.family, "version": model.version}
                for model in self.models
            ],
            "conditions": dict(conditions),
            "abstention_reasons": list(reasons),
            "observational_not_causal": True,
        }
        baseline = self._driver_baseline(first, lap_key)
        recommendation_id = self._recommendation_id(
            str(first.get("section_key", "whole-lap")),
            "conservative_fallback",
            baseline,
            provenance,
        )
        return RecommendationIdea(
            recommendation_id=recommendation_id,
            section_key=str(first.get("section_key", "whole-lap")),
            feature="conservative_fallback",
            hypothesis="Learned specifics are unsupported in these conditions.",
            cue=cue,
            learned=False,
            confidence=1.0,
            driver_baseline=baseline,
            perturbation={},
            provenance=provenance,
            abstention_reason=", ".join(reasons),
        )

    def _learned_recommendation(
        self,
        assessment: CandidateAssessment,
        section: pd.Series,
        confidence: float,
        lap_key: Optional[str],
    ) -> RecommendationIdea:
        baseline = self._driver_baseline(section, lap_key)
        provenance = {
            "schema_version": "1.0",
            "kind": "guarded-scenario-analysis",
            "models": [
                {"family": model.family, "version": model.version}
                for model in self.models
            ],
            "support": assessment.support,
            "ensemble_disagreement": assessment.disagreement,
            "relative_uncertainty": assessment.relative_uncertainty,
            "section_and_whole_lap_veto_passed": True,
            "human_achievable_bound": PERTURBATION_CAPS[assessment.feature],
            "observational_not_causal": True,
            "seconds_not_promised": True,
        }
        perturbation = {
            "from": assessment.baseline_value,
            "to": assessment.proposed_value,
            "magnitude": assessment.proposed_value - assessment.baseline_value,
        }
        recommendation_id = self._recommendation_id(
            assessment.section_key,
            assessment.feature,
            baseline,
            dict(provenance, perturbation=perturbation),
        )
        return RecommendationIdea(
            recommendation_id=recommendation_id,
            section_key=assessment.section_key,
            feature=assessment.feature,
            hypothesis=HYPOTHESES[assessment.feature],
            cue=CUES[assessment.feature],
            learned=True,
            confidence=confidence,
            driver_baseline=baseline,
            perturbation=perturbation,
            provenance=provenance,
        )

    @staticmethod
    def _driver_baseline(section: pd.Series, lap_key: Optional[str]) -> Dict[str, Any]:
        return {
            "lap_key": lap_key or str(section.get("lap_key", "")),
            "session_key": str(section.get("session_key", "")),
            "section_key": str(section.get("section_key", "")),
            "driver_consistency": float(section.get("driver_consistency", 0.0)),
            "features": {
                feature: float(section[feature]) for feature in ACTIONABLE_FEATURES
            },
        }

    def _rejection_reason(
        self,
        section_deltas: np.ndarray,
        lap_deltas: np.ndarray,
        support: float,
        disagreement: float,
        relative_uncertainty: float,
        tolerance: float,
    ) -> Optional[str]:
        if support < 0.0 or not np.isfinite(support):
            return "invalid_support"
        if support < self.minimum_support:
            return "insufficient_nearby_support"
        if not np.all(section_deltas < -1e-5):
            return "no_agreed_section_improvement"
        if not np.all(lap_deltas <= tolerance):
            return "whole_lap_veto"
        if disagreement > self.maximum_disagreement:
            return "ensemble_disagreement"
        if relative_uncertainty > self.maximum_relative_uncertainty:
            return "excessive_predictive_uncertainty"
        return None

    @staticmethod
    def _disagreement(
        section_deltas: np.ndarray, lap_deltas: np.ndarray
    ) -> float:
        section_scale = max(float(np.mean(np.abs(section_deltas))), 1e-4)
        lap_scale = max(float(np.mean(np.abs(lap_deltas))), 1e-4)
        section_disagreement = float(np.std(section_deltas) / section_scale)
        lap_disagreement = float(np.std(lap_deltas) / lap_scale)
        return max(section_disagreement, lap_disagreement)

    @staticmethod
    def _relative_uncertainty(
        row_index: int,
        baseline_scores: Sequence[Mapping[str, np.ndarray]],
        candidate_scores: Sequence[Mapping[str, np.ndarray]],
    ) -> float:
        values: List[float] = []
        for baseline, candidate in zip(baseline_scores, candidate_scores):
            section_scale = max(
                abs(float(baseline["section_expected"][row_index])), 1e-3
            )
            section_width = max(
                float(candidate["section_upper"][row_index])
                - float(candidate["section_lower"][row_index]),
                0.0,
            )
            lap_scale = max(abs(float(baseline["lap_expected"][0])), 1e-3)
            lap_width = max(
                float(candidate["lap_upper"][0]) - float(candidate["lap_lower"][0]),
                0.0,
            )
            values.extend([section_width / section_scale, lap_width / lap_scale])
        return max(values) if values else float("inf")

    @staticmethod
    def _confidence(
        support: float,
        disagreement: float,
        relative_uncertainty: float,
        section_deltas: np.ndarray,
        lap_deltas: np.ndarray,
    ) -> float:
        agreement = 1.0 / (1.0 + max(disagreement, 0.0))
        conservative_gain = min(
            abs(float(np.max(section_deltas))),
            abs(float(np.max(lap_deltas))) + 0.01,
        )
        evidence = 1.0 - np.exp(-20.0 * conservative_gain)
        calibration = 1.0 / (1.0 + max(relative_uncertainty, 0.0))
        return float(
            np.clip(
                0.45 * support
                + 0.25 * agreement
                + 0.15 * calibration
                + 0.15 * evidence,
                0.0,
                1.0,
            )
        )

    @staticmethod
    def _recommendation_id(
        section_key: str,
        feature: str,
        baseline: Mapping[str, Any],
        provenance: Mapping[str, Any],
    ) -> str:
        payload = json.dumps(
            {
                "section_key": section_key,
                "feature": feature,
                "baseline": baseline,
                "provenance": provenance,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "rec_{0}".format(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24])

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
