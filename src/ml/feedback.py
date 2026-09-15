"""Stable feedback payload contracts; no online learning is performed here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from src.core.telemetry import (
    RecommendationOutcomeContract,
    RecommendationRatingContract,
)


OUTCOME_SCHEMA_VERSION = "1.0"
RATING_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RecommendationOutcomeV1:
    recommendation_id: str
    observed_lap_key: str
    comparable: bool
    section_delta_s: Optional[float] = None
    whole_lap_delta_s: Optional[float] = None
    comparison_context: Mapping[str, Any] = field(default_factory=dict)

    def to_contract(self) -> RecommendationOutcomeContract:
        if not self.recommendation_id:
            raise ValueError("recommendation_id is required")
        if not self.observed_lap_key:
            raise ValueError("observed_lap_key is required")
        return RecommendationOutcomeContract(
            recommendation_id=self.recommendation_id,
            schema_version=OUTCOME_SCHEMA_VERSION,
            payload={
                "observed_lap_key": self.observed_lap_key,
                "comparable": bool(self.comparable),
                "section_delta_s": self.section_delta_s,
                "whole_lap_delta_s": self.whole_lap_delta_s,
                "comparison_context": dict(self.comparison_context),
                "training_eligible": False,
            },
        )


@dataclass(frozen=True)
class RecommendationRatingV1:
    recommendation_id: str
    helpful: Optional[bool] = None
    reason: Optional[str] = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_contract(self) -> RecommendationRatingContract:
        if not self.recommendation_id:
            raise ValueError("recommendation_id is required")
        return RecommendationRatingContract(
            recommendation_id=self.recommendation_id,
            schema_version=RATING_SCHEMA_VERSION,
            helpful=self.helpful,
            reason=self.reason,
            payload={
                "context": dict(self.context),
                "training_eligible": False,
            },
        )


def validate_feedback_schema(schema_version: str, kind: str) -> None:
    expected = OUTCOME_SCHEMA_VERSION if kind == "outcome" else RATING_SCHEMA_VERSION
    if kind not in ("outcome", "rating"):
        raise ValueError("kind must be 'outcome' or 'rating'")
    if schema_version != expected:
        raise ValueError(
            "Unsupported {0} schema version {1}; expected {2}".format(
                kind, schema_version, expected
            )
        )
