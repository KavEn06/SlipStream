"""Compact CPU-oriented PyTorch sequence model for profiles and pace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import torch
    from torch import nn
    import torch.nn.functional as functional
except ImportError as exc:  # pragma: no cover - exercised only in minimal installs
    torch = None  # type: ignore
    nn = None  # type: ignore
    functional = None  # type: ignore
    _TORCH_IMPORT_ERROR = exc
else:
    _TORCH_IMPORT_ERROR = None

from src.ml.dataset import (
    CATEGORICAL_FEATURES,
    PROFILE_NUMERIC_FEATURES,
    PROFILE_TARGETS,
    SECTION_MODEL_FEATURES,
    LapDataset,
)
from src.ml.sklearn_model import OptionalDependencyError, PacePrediction, ProfilePrediction


@dataclass(frozen=True)
class TorchPrediction:
    lap_keys: Tuple[str, ...]
    profiles: ProfilePrediction
    section_pace: PacePrediction
    lap_pace: PacePrediction
    ranking_score: np.ndarray


if nn is not None:

    class SequenceMultiTaskNet(nn.Module):
        """Static trace encoder plus a separate behavior branch for scenario pace."""

        def __init__(
            self,
            numeric_size: int,
            behavior_size: int,
            simulator_count: int,
            track_count: int,
            car_count: int,
            section_count: int,
            hidden_size: int = 32,
            dropout: float = 0.10,
        ):
            super().__init__()
            embedding_size = max(2, min(8, hidden_size // 4))
            self.simulator_embedding = nn.Embedding(simulator_count, embedding_size)
            self.track_embedding = nn.Embedding(track_count, embedding_size)
            self.car_embedding = nn.Embedding(car_count, embedding_size)
            combined_size = numeric_size + 3 * embedding_size
            self.input_projection = nn.Linear(combined_size, hidden_size)
            self.encoder = nn.Sequential(
                nn.Conv1d(hidden_size, hidden_size, kernel_size=5, padding=2),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Conv1d(hidden_size, hidden_size, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Dropout(dropout),
            )
            self.profile_head = nn.Conv1d(hidden_size, 4, kernel_size=1)
            self.behavior_projection = nn.Sequential(
                nn.Linear(behavior_size, hidden_size // 2),
                nn.ReLU(),
                nn.Dropout(dropout),
            )
            pace_size = hidden_size + hidden_size // 2
            self.section_head = nn.Linear(pace_size, 1)
            self.lap_head = nn.Sequential(
                nn.Linear(pace_size, hidden_size // 2),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_size // 2, 1),
            )
            self.ranking_head = nn.Sequential(
                nn.Linear(pace_size, hidden_size // 2),
                nn.ReLU(),
                nn.Linear(hidden_size // 2, 1),
            )
            self.section_count = int(section_count)

        def forward(self, sequence, simulator_id, track_id, car_id, behavior):
            sample_count = sequence.shape[1]
            identity = torch.cat(
                [
                    self.simulator_embedding(simulator_id),
                    self.track_embedding(track_id),
                    self.car_embedding(car_id),
                ],
                dim=1,
            )
            repeated_identity = identity[:, None, :].expand(-1, sample_count, -1)
            projected = torch.relu(
                self.input_projection(torch.cat([sequence, repeated_identity], dim=2))
            )
            encoded = self.encoder(projected.transpose(1, 2))

            raw_profile = self.profile_head(encoded).transpose(1, 2)
            controls = torch.sigmoid(raw_profile[:, :, :2])
            steering = torch.tanh(raw_profile[:, :, 2:3])
            speed = functional.softplus(raw_profile[:, :, 3:4])
            profiles = torch.cat([controls, steering, speed], dim=2)

            section_encoding = functional.adaptive_avg_pool1d(
                encoded, self.section_count
            ).transpose(1, 2)
            behavior_encoding = self.behavior_projection(behavior)
            pace_features = torch.cat([section_encoding, behavior_encoding], dim=2)
            section_pace = functional.softplus(self.section_head(pace_features)).squeeze(-1)
            pooled = pace_features.mean(dim=1)
            lap_pace = functional.softplus(self.lap_head(pooled)).squeeze(-1)
            ranking = self.ranking_head(pooled).squeeze(-1)
            return profiles, section_pace, lap_pace, ranking

else:

    class SequenceMultiTaskNet:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise OptionalDependencyError(
                "PyTorch is required for SequenceMultiTaskNet; install requirements.txt"
            ) from _TORCH_IMPORT_ERROR


class TorchSequenceModel:
    """Training/inference wrapper with fixed budgets and grouped validation."""

    model_type = "torch-sequence-multitask"

    def __init__(
        self,
        random_state: int = 1729,
        hidden_size: int = 32,
        dropout: float = 0.10,
        learning_rate: float = 0.003,
        batch_size: int = 8,
        max_epochs: int = 30,
        patience: int = 5,
        ranking_weight: float = 0.15,
        mc_passes: int = 12,
    ):
        if _TORCH_IMPORT_ERROR is not None:
            raise OptionalDependencyError(
                "PyTorch is required for TorchSequenceModel; install requirements.txt"
            ) from _TORCH_IMPORT_ERROR
        self.random_state = int(random_state)
        self.hidden_size = int(hidden_size)
        self.dropout = float(dropout)
        self.learning_rate = float(learning_rate)
        self.batch_size = int(batch_size)
        self.max_epochs = int(max_epochs)
        self.patience = int(patience)
        self.ranking_weight = float(ranking_weight)
        self.mc_passes = int(mc_passes)
        self.grid_points: Optional[int] = None
        self.section_count: Optional[int] = None
        self.network: Any = None
        self.category_maps: Dict[str, Dict[str, int]] = {}
        self.sequence_center: Optional[np.ndarray] = None
        self.sequence_scale: Optional[np.ndarray] = None
        self.behavior_center: Optional[np.ndarray] = None
        self.behavior_scale: Optional[np.ndarray] = None
        self.speed_scale: float = 1.0
        self.section_time_scale: float = 1.0
        self.lap_time_scale: float = 1.0
        self.training_history: List[Dict[str, float]] = []
        self.best_epoch: int = 0

    def fit(
        self,
        dataset: LapDataset,
        validation_dataset: Optional[LapDataset] = None,
    ) -> "TorchSequenceModel":
        dataset.validate()
        self._seed()
        self.grid_points = dataset.grid_points
        self.section_count = dataset.section_count
        self._fit_encoders(dataset)
        train = self._arrays(dataset, fit_scaling=True)
        validation = self._arrays(validation_dataset) if validation_dataset is not None else None
        self.network = SequenceMultiTaskNet(
            numeric_size=len(PROFILE_NUMERIC_FEATURES),
            behavior_size=len(SECTION_MODEL_FEATURES),
            simulator_count=len(self.category_maps["simulator"]),
            track_count=len(self.category_maps["track_key"]),
            car_count=len(self.category_maps["car_key"]),
            section_count=dataset.section_count,
            hidden_size=self.hidden_size,
            dropout=self.dropout,
        )
        optimizer = torch.optim.AdamW(
            self.network.parameters(),
            lr=self.learning_rate,
            weight_decay=1e-4,
        )
        generator = torch.Generator().manual_seed(self.random_state)
        best_loss = float("inf")
        best_state: Optional[Dict[str, Any]] = None
        stale_epochs = 0
        self.training_history = []
        lap_count = len(train["lap_keys"])
        for epoch in range(self.max_epochs):
            self.network.train()
            order = torch.randperm(lap_count, generator=generator).numpy()
            losses: List[float] = []
            for offset in range(0, lap_count, max(self.batch_size, 1)):
                indices = order[offset : offset + self.batch_size]
                batch = self._tensor_batch(train, indices)
                optimizer.zero_grad()
                outputs = self.network(
                    batch["sequence"],
                    batch["simulator"],
                    batch["track"],
                    batch["car"],
                    batch["behavior"],
                )
                loss = self._loss(outputs, batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.network.parameters(), max_norm=5.0)
                optimizer.step()
                losses.append(float(loss.detach().cpu().item()))

            train_loss = float(np.mean(losses)) if losses else float("inf")
            monitored_loss = (
                self._evaluation_loss(validation) if validation is not None else train_loss
            )
            self.training_history.append(
                {
                    "epoch": float(epoch),
                    "train_loss": train_loss,
                    "validation_loss": monitored_loss,
                }
            )
            if monitored_loss < best_loss - 1e-6:
                best_loss = monitored_loss
                best_state = {
                    key: value.detach().cpu().clone()
                    for key, value in self.network.state_dict().items()
                }
                self.best_epoch = epoch
                stale_epochs = 0
            else:
                stale_epochs += 1
                if stale_epochs >= self.patience:
                    break
        if best_state is not None:
            self.network.load_state_dict(best_state)
        self.network.eval()
        return self

    def predict_dataset(
        self,
        dataset: LapDataset,
        include_uncertainty: bool = True,
    ) -> TorchPrediction:
        self._require_fitted()
        arrays = self._arrays(dataset)
        passes = self.mc_passes if include_uncertainty else 1
        predictions = self._prediction_passes(arrays, passes)
        profile_distribution = predictions["profiles"]
        section_distribution = predictions["sections"]
        lap_distribution = predictions["laps"]
        expected_profiles = np.mean(profile_distribution, axis=0)
        lower_profiles = np.quantile(profile_distribution, 0.10, axis=0)
        upper_profiles = np.quantile(profile_distribution, 0.90, axis=0)
        expected_sections = np.mean(section_distribution, axis=0)
        expected_laps = np.mean(lap_distribution, axis=0)
        return TorchPrediction(
            lap_keys=tuple(arrays["lap_keys"]),
            profiles=ProfilePrediction(
                expected=expected_profiles.reshape(-1, len(PROFILE_TARGETS)),
                lower=lower_profiles.reshape(-1, len(PROFILE_TARGETS)),
                upper=upper_profiles.reshape(-1, len(PROFILE_TARGETS)),
            ),
            section_pace=PacePrediction(
                expected=expected_sections.reshape(-1),
                lower=np.quantile(section_distribution, 0.10, axis=0).reshape(-1),
                upper=np.quantile(section_distribution, 0.90, axis=0).reshape(-1),
            ),
            lap_pace=PacePrediction(
                expected=expected_laps.reshape(-1),
                lower=np.quantile(lap_distribution, 0.10, axis=0).reshape(-1),
                upper=np.quantile(lap_distribution, 0.90, axis=0).reshape(-1),
            ),
            ranking_score=np.mean(predictions["ranking"], axis=0).reshape(-1),
        )

    def predict_profiles(
        self,
        sample_frame: pd.DataFrame,
        section_frame: Optional[pd.DataFrame] = None,
    ) -> ProfilePrediction:
        dataset = self._inference_dataset(sample_frame, section_frame)
        return self.predict_dataset(dataset).profiles

    def predict_scenario(
        self,
        sample_frame: pd.DataFrame,
        section_frame: pd.DataFrame,
    ) -> Tuple[PacePrediction, PacePrediction]:
        dataset = self._inference_dataset(sample_frame, section_frame)
        prediction = self.predict_dataset(dataset)
        return prediction.section_pace, prediction.lap_pace

    def support_score(self, section_frame: pd.DataFrame) -> np.ndarray:
        """Conservative support gate based on fitted identities and valid inputs."""
        self._require_fitted()
        support = np.full(len(section_frame), 0.8, dtype=float)
        for row_index, (_, row) in enumerate(section_frame.iterrows()):
            for column in CATEGORICAL_FEATURES:
                mapping = self.category_maps.get(column, {})
                if str(row.get(column, "")) not in mapping:
                    support[row_index] *= 0.25
            numeric = pd.to_numeric(
                row[list(SECTION_MODEL_FEATURES)], errors="coerce"
            ).to_numpy(dtype=float)
            if not np.isfinite(numeric).all():
                support[row_index] = 0.0
        return np.clip(support, 0.0, 1.0)

    @staticmethod
    def condition_ood_reasons(conditions: Mapping[str, Any]) -> List[str]:
        """Apply product safety guards when training ranges are unavailable."""
        reasons: List[str] = []
        wetness = _float_or_none(
            conditions.get("wetness", conditions.get("track_wetness"))
        )
        tyre_wear = _float_or_none(
            conditions.get("tyre_wear", conditions.get("tire_wear"))
        )
        track_temp = _float_or_none(conditions.get("track_temp_c"))
        if wetness is not None and wetness >= 0.10:
            reasons.append("wet_conditions")
        if tyre_wear is not None and tyre_wear >= 0.70:
            reasons.append("high_tyre_wear")
        if track_temp is not None and track_temp <= 8.0:
            reasons.append("cold_track")
        return reasons

    def save(self, path: Path) -> None:
        self._require_fitted()
        payload = {
            "format_version": 1,
            "configuration": {
                "random_state": self.random_state,
                "hidden_size": self.hidden_size,
                "dropout": self.dropout,
                "learning_rate": self.learning_rate,
                "batch_size": self.batch_size,
                "max_epochs": self.max_epochs,
                "patience": self.patience,
                "ranking_weight": self.ranking_weight,
                "mc_passes": self.mc_passes,
            },
            "grid_points": self.grid_points,
            "section_count": self.section_count,
            "category_maps": self.category_maps,
            "sequence_center": self.sequence_center,
            "sequence_scale": self.sequence_scale,
            "behavior_center": self.behavior_center,
            "behavior_scale": self.behavior_scale,
            "speed_scale": self.speed_scale,
            "section_time_scale": self.section_time_scale,
            "lap_time_scale": self.lap_time_scale,
            "training_history": self.training_history,
            "best_epoch": self.best_epoch,
            "state_dict": self.network.state_dict(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The legacy stream format avoids archive-member names derived from the
        # temporary filename, making identical CPU state dictionaries byte-stable.
        torch.save(payload, str(path), _use_new_zipfile_serialization=False)

    @classmethod
    def load(cls, path: Path) -> "TorchSequenceModel":
        if _TORCH_IMPORT_ERROR is not None:
            raise OptionalDependencyError(
                "PyTorch is required to load this champion artifact"
            ) from _TORCH_IMPORT_ERROR
        try:
            payload = torch.load(str(path), map_location="cpu", weights_only=False)
        except TypeError:  # torch 2.0 compatibility
            payload = torch.load(str(path), map_location="cpu")
        model = cls(**payload["configuration"])
        model.grid_points = int(payload["grid_points"])
        model.section_count = int(payload["section_count"])
        model.category_maps = {
            key: {str(name): int(index) for name, index in value.items()}
            for key, value in payload["category_maps"].items()
        }
        model.sequence_center = np.asarray(payload["sequence_center"], dtype=float)
        model.sequence_scale = np.asarray(payload["sequence_scale"], dtype=float)
        model.behavior_center = np.asarray(payload["behavior_center"], dtype=float)
        model.behavior_scale = np.asarray(payload["behavior_scale"], dtype=float)
        model.speed_scale = float(payload["speed_scale"])
        model.section_time_scale = float(payload["section_time_scale"])
        model.lap_time_scale = float(payload["lap_time_scale"])
        model.training_history = list(payload.get("training_history", []))
        model.best_epoch = int(payload.get("best_epoch", 0))
        model.network = SequenceMultiTaskNet(
            numeric_size=len(PROFILE_NUMERIC_FEATURES),
            behavior_size=len(SECTION_MODEL_FEATURES),
            simulator_count=len(model.category_maps["simulator"]),
            track_count=len(model.category_maps["track_key"]),
            car_count=len(model.category_maps["car_key"]),
            section_count=model.section_count,
            hidden_size=model.hidden_size,
            dropout=model.dropout,
        )
        model.network.load_state_dict(payload["state_dict"])
        model.network.eval()
        return model

    def metadata(self) -> Dict[str, Any]:
        self._require_fitted()
        return {
            "model_type": self.model_type,
            "random_state": self.random_state,
            "hidden_size": self.hidden_size,
            "dropout": self.dropout,
            "grid_points": self.grid_points,
            "section_count": self.section_count,
            "best_epoch": self.best_epoch,
            "max_epochs": self.max_epochs,
            "profile_targets": list(PROFILE_TARGETS),
            "tasks": ["expected_profiles", "section_pace", "lap_pace", "pairwise_ranking"],
            "device": "cpu",
        }

    def _fit_encoders(self, dataset: LapDataset) -> None:
        for column in CATEGORICAL_FEATURES:
            values = sorted(dataset.lap_frame[column].astype(str).unique())
            mapping = {"<unknown>": 0}
            mapping.update({value: index + 1 for index, value in enumerate(values)})
            self.category_maps[column] = mapping

    def _arrays(
        self,
        dataset: Optional[LapDataset],
        fit_scaling: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if dataset is None:
            return None
        lap_order = dataset.lap_frame["lap_key"].astype(str).tolist()
        sequences: List[np.ndarray] = []
        behaviors: List[np.ndarray] = []
        profiles: List[np.ndarray] = []
        section_times: List[np.ndarray] = []
        lap_times: List[float] = []
        identities: Dict[str, List[int]] = {column: [] for column in CATEGORICAL_FEATURES}
        weights: List[float] = []
        for lap_key in lap_order:
            sample_rows = (
                dataset.sample_frame[dataset.sample_frame["lap_key"] == lap_key]
                .sort_values("progress")
            )
            section_rows = (
                dataset.section_frame[dataset.section_frame["lap_key"] == lap_key]
                .sort_values("section_index")
            )
            lap_row = dataset.lap_frame[dataset.lap_frame["lap_key"] == lap_key].iloc[0]
            sequences.append(
                sample_rows[list(PROFILE_NUMERIC_FEATURES)]
                .apply(pd.to_numeric, errors="coerce")
                .to_numpy(dtype=float)
            )
            behaviors.append(
                section_rows[list(SECTION_MODEL_FEATURES)]
                .apply(pd.to_numeric, errors="coerce")
                .to_numpy(dtype=float)
            )
            profiles.append(sample_rows[list(PROFILE_TARGETS)].to_numpy(dtype=float))
            section_times.append(section_rows["section_time_s"].to_numpy(dtype=float))
            lap_times.append(float(lap_row["lap_time_s"]))
            weights.append(float(lap_row.get("sample_weight", 1.0)))
            for column in CATEGORICAL_FEATURES:
                mapping = self.category_maps[column]
                identities[column].append(mapping.get(str(lap_row[column]), 0))

        sequence_array = np.stack(sequences)
        behavior_array = np.stack(behaviors)
        profile_array = np.stack(profiles)
        section_array = np.stack(section_times)
        lap_array = np.asarray(lap_times, dtype=float)
        if fit_scaling:
            self.sequence_center, self.sequence_scale = self._center_scale(sequence_array)
            self.behavior_center, self.behavior_scale = self._center_scale(behavior_array)
            self.speed_scale = max(float(np.nanpercentile(profile_array[:, :, 3], 99)), 1.0)
            self.section_time_scale = max(float(np.nanmedian(section_array)), 1e-3)
            self.lap_time_scale = max(float(np.nanmedian(lap_array)), 1e-3)
        self._require_scaling()
        sequence_array = self._normalize(
            sequence_array, self.sequence_center, self.sequence_scale
        )
        behavior_array = self._normalize(
            behavior_array, self.behavior_center, self.behavior_scale
        )
        profile_array = profile_array.copy()
        profile_array[:, :, 3] /= self.speed_scale
        return {
            "lap_keys": lap_order,
            "sequence": sequence_array.astype(np.float32),
            "behavior": behavior_array.astype(np.float32),
            "profiles": profile_array.astype(np.float32),
            "sections": (section_array / self.section_time_scale).astype(np.float32),
            "laps": (lap_array / self.lap_time_scale).astype(np.float32),
            "simulator": np.asarray(identities["simulator"], dtype=np.int64),
            "track": np.asarray(identities["track_key"], dtype=np.int64),
            "car": np.asarray(identities["car_key"], dtype=np.int64),
            "weights": np.asarray(weights, dtype=np.float32),
        }

    def _tensor_batch(
        self, arrays: Dict[str, Any], indices: Sequence[int]
    ) -> Dict[str, Any]:
        return {
            "sequence": torch.as_tensor(arrays["sequence"][indices]),
            "behavior": torch.as_tensor(arrays["behavior"][indices]),
            "profiles": torch.as_tensor(arrays["profiles"][indices]),
            "sections": torch.as_tensor(arrays["sections"][indices]),
            "laps": torch.as_tensor(arrays["laps"][indices]),
            "simulator": torch.as_tensor(arrays["simulator"][indices]),
            "track": torch.as_tensor(arrays["track"][indices]),
            "car": torch.as_tensor(arrays["car"][indices]),
            "weights": torch.as_tensor(arrays["weights"][indices]),
        }

    def _loss(self, outputs: Tuple[Any, ...], batch: Mapping[str, Any]) -> Any:
        profiles, sections, laps, ranking = outputs
        weights = batch["weights"]
        profile_error = ((profiles - batch["profiles"]) ** 2).mean(dim=(1, 2))
        section_error = ((sections - batch["sections"]) ** 2).mean(dim=1)
        lap_error = (laps - batch["laps"]) ** 2
        regression = (
            0.55 * profile_error + 0.20 * section_error + 0.25 * lap_error
        )
        regression_loss = (regression * weights).sum() / torch.clamp(weights.sum(), min=1e-6)
        ranking_loss = self._ranking_loss(ranking, batch["laps"])
        return regression_loss + self.ranking_weight * ranking_loss

    @staticmethod
    def _ranking_loss(ranking: Any, normalized_lap_times: Any) -> Any:
        if len(ranking) < 2:
            return ranking.sum() * 0.0
        differences = ranking[:, None] - ranking[None, :]
        target = normalized_lap_times[None, :] - normalized_lap_times[:, None]
        mask = torch.triu(torch.ones_like(target, dtype=torch.bool), diagonal=1)
        non_ties = mask & (torch.abs(target) > 1e-6)
        if not torch.any(non_ties):
            return ranking.sum() * 0.0
        signs = torch.sign(target[non_ties])
        return functional.softplus(-signs * differences[non_ties]).mean()

    def _evaluation_loss(self, arrays: Optional[Dict[str, Any]]) -> float:
        if arrays is None:
            return float("inf")
        self.network.eval()
        with torch.no_grad():
            indices = np.arange(len(arrays["lap_keys"]))
            batch = self._tensor_batch(arrays, indices)
            outputs = self.network(
                batch["sequence"],
                batch["simulator"],
                batch["track"],
                batch["car"],
                batch["behavior"],
            )
            return float(self._loss(outputs, batch).cpu().item())

    def _prediction_passes(
        self, arrays: Dict[str, Any], passes: int
    ) -> Dict[str, np.ndarray]:
        results: Dict[str, List[np.ndarray]] = {
            "profiles": [],
            "sections": [],
            "laps": [],
            "ranking": [],
        }
        indices = np.arange(len(arrays["lap_keys"]))
        batch = self._tensor_batch(arrays, indices)
        for pass_index in range(max(int(passes), 1)):
            torch.manual_seed(self.random_state + 1000 + pass_index)
            if passes > 1:
                self.network.train()
            else:
                self.network.eval()
            with torch.no_grad():
                profiles, sections, laps, ranking = self.network(
                    batch["sequence"],
                    batch["simulator"],
                    batch["track"],
                    batch["car"],
                    batch["behavior"],
                )
            profile_values = profiles.cpu().numpy()
            profile_values[:, :, 3] *= self.speed_scale
            results["profiles"].append(profile_values)
            results["sections"].append(sections.cpu().numpy() * self.section_time_scale)
            results["laps"].append(laps.cpu().numpy() * self.lap_time_scale)
            results["ranking"].append(ranking.cpu().numpy())
        self.network.eval()
        return {key: np.stack(values, axis=0) for key, values in results.items()}

    def _inference_dataset(
        self,
        sample_frame: pd.DataFrame,
        section_frame: Optional[pd.DataFrame],
    ) -> LapDataset:
        if section_frame is None:
            raise ValueError("section_frame is required for sequence-model inference")
        sample = sample_frame.copy()
        sections = section_frame.copy()
        if "lap_key" not in sample:
            sample["lap_key"] = "inference-lap"
        if "lap_key" not in sections:
            sections["lap_key"] = "inference-lap"
        lap_records = []
        for lap_key, group in sections.groupby("lap_key", sort=False):
            first = group.iloc[0]
            lap_records.append(
                {
                    "lap_key": str(lap_key),
                    "session_key": str(first.get("session_key", "inference-session")),
                    "simulator": str(first.get("simulator", "unknown-simulator")),
                    "track_key": str(first.get("track_key", "unknown-track")),
                    "car_key": str(first.get("car_key", "unknown-car")),
                    "lap_time_s": float(first.get("lap_time_s", 1.0)),
                    "sample_weight": 1.0,
                }
            )
        return LapDataset(
            sample_frame=sample,
            section_frame=sections,
            lap_frame=pd.DataFrame(lap_records),
            grid_points=int(self.grid_points),
            section_count=int(self.section_count),
            source_revisions={},
        )

    @staticmethod
    def _center_scale(values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        center = np.nanmedian(values, axis=(0, 1))
        center[~np.isfinite(center)] = 0.0
        filled = np.where(np.isfinite(values), values, center[None, None, :])
        scale = np.nanstd(filled, axis=(0, 1))
        scale[scale < 1e-6] = 1.0
        return center.astype(float), scale.astype(float)

    @staticmethod
    def _normalize(
        values: np.ndarray, center: np.ndarray, scale: np.ndarray
    ) -> np.ndarray:
        filled = np.where(np.isfinite(values), values, center[None, None, :])
        return (filled - center[None, None, :]) / scale[None, None, :]

    def _seed(self) -> None:
        random.seed(self.random_state)
        np.random.seed(self.random_state)
        torch.manual_seed(self.random_state)
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.set_num_threads(1)

    def _require_scaling(self) -> None:
        if (
            self.sequence_center is None
            or self.sequence_scale is None
            or self.behavior_center is None
            or self.behavior_scale is None
        ):
            raise RuntimeError("TorchSequenceModel scaling metadata is unavailable")

    def _require_fitted(self) -> None:
        if self.network is None:
            raise RuntimeError("TorchSequenceModel must be fitted before inference")
        self._require_scaling()


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
