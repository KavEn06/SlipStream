"""Scikit-learn expected-profile and pace models with tree uncertainty bands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
except ImportError as exc:  # pragma: no cover - exercised only in minimal installs
    ColumnTransformer = None  # type: ignore
    RandomForestRegressor = None  # type: ignore
    SimpleImputer = None  # type: ignore
    Pipeline = None  # type: ignore
    OneHotEncoder = None  # type: ignore
    _SKLEARN_IMPORT_ERROR = exc
else:
    _SKLEARN_IMPORT_ERROR = None

from src.ml.dataset import (
    ACTIONABLE_FEATURES,
    CATEGORICAL_FEATURES,
    PROFILE_NUMERIC_FEATURES,
    PROFILE_TARGETS,
    SECTION_MODEL_FEATURES,
    LapDataset,
)


class OptionalDependencyError(ImportError):
    pass


@dataclass(frozen=True)
class ProfilePrediction:
    expected: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    target_names: Tuple[str, ...] = PROFILE_TARGETS


@dataclass(frozen=True)
class PacePrediction:
    expected: np.ndarray
    lower: np.ndarray
    upper: np.ndarray


def lap_numeric_features(section_count: int) -> Tuple[str, ...]:
    columns: List[str] = [
        "driver_consistency",
        "lap_consistency",
        "track_length_m",
        "wetness",
        "air_temp_c",
        "track_temp_c",
        "tyre_wear",
    ]
    columns.extend("mean_{0}".format(feature) for feature in ACTIONABLE_FEATURES)
    for section_index in range(section_count):
        columns.extend(
            "s{0}_{1}".format(section_index, feature) for feature in ACTIONABLE_FEATURES
        )
    return tuple(columns)


class SklearnProfileModel:
    """A global forest with explicit simulator/track/car calibration."""

    model_type = "sklearn-random-forest"

    def __init__(
        self,
        random_state: int = 1729,
        n_estimators: int = 64,
        max_depth: Optional[int] = 12,
        min_samples_leaf: int = 2,
        n_jobs: int = 1,
        interval: Tuple[float, float] = (0.10, 0.90),
    ):
        if _SKLEARN_IMPORT_ERROR is not None:
            raise OptionalDependencyError(
                "scikit-learn is required for SklearnProfileModel; install requirements.txt"
            ) from _SKLEARN_IMPORT_ERROR
        if not 0.0 < interval[0] < interval[1] < 1.0:
            raise ValueError("interval quantiles must be ordered inside (0, 1)")
        self.random_state = int(random_state)
        self.n_estimators = int(n_estimators)
        self.max_depth = max_depth
        self.min_samples_leaf = int(min_samples_leaf)
        self.n_jobs = int(n_jobs)
        self.interval = interval
        self.grid_points: Optional[int] = None
        self.section_count: Optional[int] = None
        self.profile_pipeline: Any = None
        self.section_pipeline: Any = None
        self.lap_pipeline: Any = None
        self.profile_residual_band: Optional[np.ndarray] = None
        self.section_residual_band: float = 0.0
        self.lap_residual_band: float = 0.0
        self._support_reference: Optional[pd.DataFrame] = None
        self._support_center: Optional[np.ndarray] = None
        self._support_scale: Optional[np.ndarray] = None
        self._distance_scale: float = 1.0
        self._feature_ranges: Dict[Tuple[str, str], Dict[str, Tuple[float, float]]] = {}
        self._condition_ranges: Dict[str, Tuple[float, float]] = {}
        self._seen_combinations: set = set()

    def fit(self, dataset: LapDataset) -> "SklearnProfileModel":
        dataset.validate()
        self.grid_points = dataset.grid_points
        self.section_count = dataset.section_count
        forest_parameters = {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "min_samples_leaf": self.min_samples_leaf,
            "random_state": self.random_state,
            "n_jobs": self.n_jobs,
            "bootstrap": True,
            "oob_score": True,
            "max_features": 0.8,
        }
        self.profile_pipeline = Pipeline(
            [
                ("features", self._preprocessor(PROFILE_NUMERIC_FEATURES, CATEGORICAL_FEATURES)),
                ("model", RandomForestRegressor(**forest_parameters)),
            ]
        )
        section_categorical = CATEGORICAL_FEATURES + ("section_phase",)
        self.section_pipeline = Pipeline(
            [
                ("features", self._preprocessor(SECTION_MODEL_FEATURES, section_categorical)),
                (
                    "model",
                    RandomForestRegressor(
                        **dict(forest_parameters, random_state=self.random_state + 1)
                    ),
                ),
            ]
        )
        lap_features = lap_numeric_features(dataset.section_count)
        self.lap_pipeline = Pipeline(
            [
                ("features", self._preprocessor(lap_features, CATEGORICAL_FEATURES)),
                (
                    "model",
                    RandomForestRegressor(
                        **dict(forest_parameters, random_state=self.random_state + 2)
                    ),
                ),
            ]
        )

        samples = dataset.sample_frame
        sections = dataset.section_frame
        laps = dataset.lap_frame
        self.profile_pipeline.fit(
            samples,
            samples[list(PROFILE_TARGETS)].to_numpy(dtype=float),
            model__sample_weight=samples["sample_weight"].to_numpy(dtype=float),
        )
        self.section_pipeline.fit(
            sections,
            sections["section_time_s"].to_numpy(dtype=float),
            model__sample_weight=sections["sample_weight"].to_numpy(dtype=float),
        )
        self.lap_pipeline.fit(
            laps,
            laps["lap_time_s"].to_numpy(dtype=float),
            model__sample_weight=laps["sample_weight"].to_numpy(dtype=float),
        )

        profile_oob = np.asarray(self.profile_pipeline.named_steps["model"].oob_prediction_)
        profile_target = samples[list(PROFILE_TARGETS)].to_numpy(dtype=float)
        self.profile_residual_band = self._residual_quantile(profile_target, profile_oob, axis=0)
        section_oob = np.asarray(self.section_pipeline.named_steps["model"].oob_prediction_)
        self.section_residual_band = float(
            self._residual_quantile(
                sections["section_time_s"].to_numpy(dtype=float), section_oob
            )
        )
        lap_oob = np.asarray(self.lap_pipeline.named_steps["model"].oob_prediction_)
        self.lap_residual_band = float(
            self._residual_quantile(laps["lap_time_s"].to_numpy(dtype=float), lap_oob)
        )
        self._fit_support(sections)
        self._seen_combinations = set(
            zip(
                laps["simulator"].astype(str),
                laps["track_key"].astype(str),
                laps["car_key"].astype(str),
            )
        )
        for condition in ("wetness", "air_temp_c", "track_temp_c", "tyre_wear"):
            values = pd.to_numeric(sections[condition], errors="coerce").dropna()
            if not values.empty:
                self._condition_ranges[condition] = (
                    float(values.quantile(0.01)),
                    float(values.quantile(0.99)),
                )
        return self

    def predict_profiles(self, sample_frame: pd.DataFrame) -> ProfilePrediction:
        self._require_fitted()
        expected = np.asarray(self.profile_pipeline.predict(sample_frame), dtype=float)
        distribution = self._forest_distribution(self.profile_pipeline, sample_frame)
        lower = np.quantile(distribution, self.interval[0], axis=0)
        upper = np.quantile(distribution, self.interval[1], axis=0)
        residual = np.asarray(self.profile_residual_band, dtype=float)
        lower = np.minimum(lower, expected - residual)
        upper = np.maximum(upper, expected + residual)
        expected, lower, upper = self._clip_profile(expected, lower, upper)
        penalty = self._unknown_combination_penalty(sample_frame)
        if np.any(penalty > 0):
            lower -= penalty[:, None] * residual[None, :]
            upper += penalty[:, None] * residual[None, :]
            expected, lower, upper = self._clip_profile(expected, lower, upper)
        return ProfilePrediction(expected=expected, lower=lower, upper=upper)

    def predict_section_pace(self, section_frame: pd.DataFrame) -> PacePrediction:
        self._require_fitted()
        expected = np.asarray(self.section_pipeline.predict(section_frame), dtype=float).reshape(-1)
        distribution = self._forest_distribution(self.section_pipeline, section_frame)
        lower = np.quantile(distribution, self.interval[0], axis=0).reshape(-1)
        upper = np.quantile(distribution, self.interval[1], axis=0).reshape(-1)
        lower = np.minimum(lower, expected - self.section_residual_band)
        upper = np.maximum(upper, expected + self.section_residual_band)
        return PacePrediction(expected=expected, lower=np.maximum(lower, 0.0), upper=upper)

    def predict_lap_pace(self, sections_or_laps: pd.DataFrame) -> PacePrediction:
        self._require_fitted()
        if "lap_time_s" in sections_or_laps and "section_key" not in sections_or_laps:
            lap_frame = sections_or_laps
        elif "section_key" in sections_or_laps:
            lap_frame = sections_to_lap_frame(sections_or_laps, int(self.section_count))
        else:
            lap_frame = sections_or_laps
        expected = np.asarray(self.lap_pipeline.predict(lap_frame), dtype=float).reshape(-1)
        distribution = self._forest_distribution(self.lap_pipeline, lap_frame)
        lower = np.quantile(distribution, self.interval[0], axis=0).reshape(-1)
        upper = np.quantile(distribution, self.interval[1], axis=0).reshape(-1)
        lower = np.minimum(lower, expected - self.lap_residual_band)
        upper = np.maximum(upper, expected + self.lap_residual_band)
        return PacePrediction(expected=expected, lower=np.maximum(lower, 0.0), upper=upper)

    def support_score(self, section_frame: pd.DataFrame) -> np.ndarray:
        self._require_fitted()
        numeric = self._support_matrix(section_frame)
        reference = self._support_matrix(self._support_reference)
        distances = np.sqrt(
            np.sum((numeric[:, None, :] - reference[None, :, :]) ** 2, axis=2)
        )
        nearest = np.min(distances, axis=1)
        support = np.exp(-nearest / max(self._distance_scale, 1e-6))
        for row_index, (_, row) in enumerate(section_frame.iterrows()):
            combination = (
                str(row.get("simulator", "")),
                str(row.get("track_key", "")),
                str(row.get("car_key", "")),
            )
            if combination not in self._seen_combinations:
                support[row_index] *= 0.25
            ranges = self.feature_bounds(str(row.get("track_key")), str(row.get("car_key")))
            for feature in ACTIONABLE_FEATURES:
                low, high = ranges.get(feature, (-np.inf, np.inf))
                value = float(row.get(feature, np.nan))
                if not np.isfinite(value) or value < low or value > high:
                    support[row_index] *= 0.5
        return np.clip(support, 0.0, 1.0)

    def feature_bounds(self, track_key: str, car_key: str) -> Dict[str, Tuple[float, float]]:
        exact = self._feature_ranges.get((str(track_key), str(car_key)))
        if exact is not None:
            return dict(exact)
        combined: Dict[str, List[float]] = {feature: [] for feature in ACTIONABLE_FEATURES}
        for ranges in self._feature_ranges.values():
            for feature, bounds in ranges.items():
                combined[feature].extend(bounds)
        return {
            feature: (min(values), max(values))
            for feature, values in combined.items()
            if values
        }

    def condition_ood_reasons(self, conditions: Mapping[str, Any]) -> List[str]:
        reasons: List[str] = []
        for name, bounds in self._condition_ranges.items():
            value = conditions.get(name)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                reasons.append("invalid_{0}".format(name))
                continue
            margin = max((bounds[1] - bounds[0]) * 0.10, 0.02)
            if numeric < bounds[0] - margin or numeric > bounds[1] + margin:
                reasons.append("unsupported_{0}".format(name))
        return reasons

    def metadata(self) -> Dict[str, Any]:
        self._require_fitted()
        return {
            "model_type": self.model_type,
            "random_state": self.random_state,
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "min_samples_leaf": self.min_samples_leaf,
            "interval_quantiles": list(self.interval),
            "grid_points": self.grid_points,
            "section_count": self.section_count,
            "profile_targets": list(PROFILE_TARGETS),
            "global_calibration": list(CATEGORICAL_FEATURES),
            "condition_ranges": {
                key: list(value) for key, value in self._condition_ranges.items()
            },
        }

    @staticmethod
    def _preprocessor(
        numeric_features: Sequence[str], categorical_features: Sequence[str]
    ) -> Any:
        numeric_pipeline = Pipeline(
            [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
        )
        categorical_pipeline = Pipeline(
            [
                ("impute", SimpleImputer(strategy="most_frequent")),
                (
                    "onehot",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ),
            ]
        )
        return ColumnTransformer(
            [
                ("numeric", numeric_pipeline, list(numeric_features)),
                ("categorical", categorical_pipeline, list(categorical_features)),
            ],
            remainder="drop",
        )

    @staticmethod
    def _forest_distribution(pipeline: Any, frame: pd.DataFrame) -> np.ndarray:
        transformed = pipeline.named_steps["features"].transform(frame)
        predictions = [
            np.asarray(estimator.predict(transformed), dtype=float)
            for estimator in pipeline.named_steps["model"].estimators_
        ]
        return np.stack(predictions, axis=0)

    @staticmethod
    def _residual_quantile(
        target: np.ndarray, prediction: np.ndarray, axis: Optional[int] = None
    ) -> np.ndarray:
        target_array = np.asarray(target, dtype=float)
        prediction_array = np.asarray(prediction, dtype=float)
        residual = np.abs(target_array - prediction_array)
        finite = np.isfinite(residual)
        if axis is None:
            values = residual[finite]
            return np.asarray(float(np.quantile(values, 0.90)) if len(values) else 0.0)
        result = []
        for column in range(residual.shape[1]):
            values = residual[:, column][finite[:, column]]
            result.append(float(np.quantile(values, 0.90)) if len(values) else 0.0)
        return np.asarray(result, dtype=float)

    def _fit_support(self, sections: pd.DataFrame) -> None:
        self._support_reference = sections[
            list(SECTION_MODEL_FEATURES) + list(CATEGORICAL_FEATURES)
        ].copy().reset_index(drop=True)
        raw = sections[list(SECTION_MODEL_FEATURES)].apply(pd.to_numeric, errors="coerce")
        center = raw.median(axis=0).fillna(0.0).to_numpy(dtype=float)
        filled = raw.fillna(pd.Series(center, index=raw.columns)).to_numpy(dtype=float)
        scale = np.nanstd(filled, axis=0)
        scale[scale < 1e-6] = 1.0
        self._support_center = center
        self._support_scale = scale
        normalized = (filled - center) / scale
        if len(normalized) > 1:
            pairwise = np.sqrt(
                np.sum((normalized[:, None, :] - normalized[None, :, :]) ** 2, axis=2)
            )
            pairwise[pairwise == 0] = np.nan
            nearest = np.nanmin(pairwise, axis=1)
            finite = nearest[np.isfinite(nearest)]
            self._distance_scale = max(
                float(np.quantile(finite, 0.90)) if len(finite) else 1.0,
                0.25,
            )
        for (track_key, car_key), group in sections.groupby(["track_key", "car_key"]):
            self._feature_ranges[(str(track_key), str(car_key))] = {
                feature: (
                    float(pd.to_numeric(group[feature], errors="coerce").quantile(0.02)),
                    float(pd.to_numeric(group[feature], errors="coerce").quantile(0.98)),
                )
                for feature in ACTIONABLE_FEATURES
            }

    def _support_matrix(self, frame: Optional[pd.DataFrame]) -> np.ndarray:
        if frame is None or self._support_center is None or self._support_scale is None:
            raise RuntimeError("Support reference is unavailable")
        raw = frame[list(SECTION_MODEL_FEATURES)].apply(pd.to_numeric, errors="coerce")
        filled = raw.fillna(
            pd.Series(self._support_center, index=list(SECTION_MODEL_FEATURES))
        ).to_numpy(dtype=float)
        return (filled - self._support_center) / self._support_scale

    def _unknown_combination_penalty(self, frame: pd.DataFrame) -> np.ndarray:
        penalties = []
        for _, row in frame.iterrows():
            combination = (
                str(row.get("simulator", "")),
                str(row.get("track_key", "")),
                str(row.get("car_key", "")),
            )
            penalties.append(1.0 if combination not in self._seen_combinations else 0.0)
        return np.asarray(penalties, dtype=float)

    @staticmethod
    def _clip_profile(
        expected: np.ndarray, lower: np.ndarray, upper: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        for column in (0, 1):
            expected[:, column] = np.clip(expected[:, column], 0.0, 1.0)
            lower[:, column] = np.clip(lower[:, column], 0.0, 1.0)
            upper[:, column] = np.clip(upper[:, column], 0.0, 1.0)
        expected[:, 2] = np.clip(expected[:, 2], -1.0, 1.0)
        lower[:, 2] = np.clip(lower[:, 2], -1.0, 1.0)
        upper[:, 2] = np.clip(upper[:, 2], -1.0, 1.0)
        expected[:, 3] = np.maximum(expected[:, 3], 0.0)
        lower[:, 3] = np.maximum(lower[:, 3], 0.0)
        upper[:, 3] = np.maximum(upper[:, 3], 0.0)
        lower = np.minimum(lower, expected)
        upper = np.maximum(upper, expected)
        return expected, lower, upper

    def _require_fitted(self) -> None:
        if self.profile_pipeline is None or self.section_pipeline is None or self.lap_pipeline is None:
            raise RuntimeError("SklearnProfileModel must be fitted before inference")


def sections_to_lap_frame(section_frame: pd.DataFrame, section_count: int) -> pd.DataFrame:
    if section_frame.empty:
        raise ValueError("At least one section is required")
    group_column = "lap_key" if "lap_key" in section_frame else None
    groups: Iterable[Tuple[Any, pd.DataFrame]]
    if group_column is None:
        groups = [("scenario-lap", section_frame)]
    else:
        groups = section_frame.groupby(group_column, sort=False)
    records: List[Dict[str, Any]] = []
    for lap_key, sections in groups:
        ordered = sections.sort_values("section_index")
        first = ordered.iloc[0]
        record: Dict[str, Any] = {
            "lap_key": str(lap_key),
            "session_key": str(first.get("session_key", "scenario-session")),
            "simulator": str(first.get("simulator", "unknown-simulator")),
            "track_key": str(first.get("track_key", "unknown-track")),
            "car_key": str(first.get("car_key", "unknown-car")),
            "lap_time_s": float(first.get("lap_time_s", 0.0)),
            "driver_consistency": float(first.get("driver_consistency", 0.0)),
            "lap_consistency": float(first.get("lap_consistency", 0.0)),
            "track_length_m": float(first.get("track_length_m", 0.0)),
            "wetness": first.get("wetness", np.nan),
            "air_temp_c": first.get("air_temp_c", np.nan),
            "track_temp_c": first.get("track_temp_c", np.nan),
            "tyre_wear": first.get("tyre_wear", np.nan),
        }
        for feature in ACTIONABLE_FEATURES:
            record["mean_{0}".format(feature)] = float(ordered[feature].mean())
        by_index = {int(row["section_index"]): row for _, row in ordered.iterrows()}
        for section_index in range(section_count):
            row = by_index.get(section_index, first)
            for feature in ACTIONABLE_FEATURES:
                record["s{0}_{1}".format(section_index, feature)] = float(row[feature])
        records.append(record)
    return pd.DataFrame(records)
