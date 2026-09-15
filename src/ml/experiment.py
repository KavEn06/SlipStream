"""Reproducible offline search, immutable evaluation, and champion selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy.orm import Session

from src.ml.dataset import (
    PROFILE_TARGETS,
    GroupedSplit,
    LapDataset,
    grouped_cv_splits,
    immutable_group_split,
)
from src.ml.evaluation import (
    average_metrics,
    evaluate_sklearn_model,
    evaluate_torch_model,
)
from src.ml.registry import MODEL_NAME, ModelRegistry
from src.ml.sklearn_model import OptionalDependencyError, SklearnProfileModel
from src.ml.torch_model import TorchSequenceModel


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int = 1729
    holdout_fraction: float = 0.20
    holdout_salt: str = "slipstream-holdout-v1"
    cv_folds: int = 3
    sklearn_search_budget: int = 3
    torch_search_budget: int = 2
    include_torch: bool = True
    sklearn_estimators: int = 64
    torch_max_epochs: int = 20
    torch_patience: int = 4
    torch_batch_size: int = 8


@dataclass(frozen=True)
class CandidateResult:
    family: str
    version: str
    model_version_id: int
    cv_composite_score: float
    holdout_metrics: Mapping[str, float]
    search_parameters: Mapping[str, Any]
    status: str


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    model_name: str
    champion_version: str
    champion_model_version_id: int
    split: GroupedSplit
    candidates: Tuple[CandidateResult, ...]
    dataset_fingerprint: str
    sample_rows: int
    effective_laps: int


class OfflineExperimentRunner:
    def __init__(
        self,
        model_root: Path,
        config: Optional[ExperimentConfig] = None,
        model_name: str = MODEL_NAME,
    ):
        self.model_root = Path(model_root)
        self.config = config or ExperimentConfig()
        self.model_name = model_name

    def run(self, dataset: LapDataset, database_session: Session) -> ExperimentResult:
        dataset.validate()
        self._seed_everything()
        split = immutable_group_split(
            dataset,
            holdout_fraction=self.config.holdout_fraction,
            salt=self.config.holdout_salt,
        )
        train_dataset = dataset.subset(split.train_lap_keys)
        holdout_dataset = dataset.subset(split.holdout_lap_keys)
        folds = grouped_cv_splits(
            train_dataset,
            n_splits=self.config.cv_folds,
            prefer_session=True,
        )
        experiment_id = self._experiment_id(dataset)
        registry = ModelRegistry(
            database_session,
            self.model_root,
            model_name=self.model_name,
        )

        finalists: List[Dict[str, Any]] = []
        sklearn_model, sklearn_parameters, sklearn_cv, sklearn_trials = self._search_sklearn(
            train_dataset, folds
        )
        sklearn_holdout = evaluate_sklearn_model(sklearn_model, holdout_dataset)
        finalists.append(
            {
                "family": "sklearn",
                "model": sklearn_model,
                "parameters": sklearn_parameters,
                "cv": sklearn_cv,
                "trials": sklearn_trials,
                "holdout": sklearn_holdout,
            }
        )

        if self.config.include_torch:
            try:
                torch_finalist = self._search_torch(train_dataset, folds)
            except OptionalDependencyError:
                torch_finalist = None
            if torch_finalist is not None:
                torch_model, torch_parameters, torch_cv, torch_trials = torch_finalist
                finalists.append(
                    {
                        "family": "torch",
                        "model": torch_model,
                        "parameters": torch_parameters,
                        "cv": torch_cv,
                        "trials": torch_trials,
                        "holdout": evaluate_torch_model(torch_model, holdout_dataset),
                    }
                )

        dataset_metadata = {
            "fingerprint": dataset.fingerprint(),
            "sample_rows": dataset.sample_row_count,
            "effective_laps": dataset.effective_lap_count,
            "grid_points": dataset.grid_points,
            "section_count": dataset.section_count,
            "source_revisions": dict(dataset.source_revisions),
            "holdout_salt": split.salt,
            "holdout_group_kind": split.group_kind,
            "holdout_groups": list(split.holdout_groups),
            "selection_metric": "grouped_cv.composite_score",
            "holdout_used_for_selection": False,
        }
        registered: List[Tuple[Dict[str, Any], Any, str]] = []
        for finalist in finalists:
            version = "{0}-{1}".format(experiment_id, finalist["family"])
            cv_metrics = dict(finalist["cv"])
            for trial_index, trial in enumerate(finalist["trials"]):
                cv_metrics["search_trial_{0}_composite_score".format(trial_index)] = float(
                    trial["metrics"]["composite_score"]
                )
            profile = self._holdout_profile(
                finalist["model"], finalist["family"], holdout_dataset
            )
            row = registry.register(
                finalist["model"],
                version,
                metrics_by_split={
                    "grouped_cv": cv_metrics,
                    "immutable_holdout": finalist["holdout"],
                },
                dataset_metadata=dict(
                    dataset_metadata,
                    search_parameters=dict(finalist["parameters"]),
                ),
                holdout_profile=profile,
            )
            registered.append((finalist, row, version))

        selected_finalist, selected_row, selected_version = min(
            registered,
            key=lambda item: (
                float(item[0]["cv"]["composite_score"]),
                item[0]["family"],
            ),
        )
        registry.promote(selected_row.id)
        candidate_results: List[CandidateResult] = []
        for finalist, row, version in registered:
            status = "champion" if row.id == selected_row.id else "challenger"
            candidate_results.append(
                CandidateResult(
                    family=str(finalist["family"]),
                    version=version,
                    model_version_id=int(row.id),
                    cv_composite_score=float(finalist["cv"]["composite_score"]),
                    holdout_metrics=dict(finalist["holdout"]),
                    search_parameters=dict(finalist["parameters"]),
                    status=status,
                )
            )
        return ExperimentResult(
            experiment_id=experiment_id,
            model_name=self.model_name,
            champion_version=selected_version,
            champion_model_version_id=int(selected_row.id),
            split=split,
            candidates=tuple(candidate_results),
            dataset_fingerprint=dataset.fingerprint(),
            sample_rows=dataset.sample_row_count,
            effective_laps=dataset.effective_lap_count,
        )

    def _search_sklearn(
        self,
        train_dataset: LapDataset,
        folds: Sequence[Tuple[Sequence[str], Sequence[str]]],
    ) -> Tuple[
        SklearnProfileModel,
        Mapping[str, Any],
        Mapping[str, float],
        List[Mapping[str, Any]],
    ]:
        candidates = [
            {
                "n_estimators": max(24, self.config.sklearn_estimators // 2),
                "max_depth": 8,
                "min_samples_leaf": 2,
            },
            {
                "n_estimators": self.config.sklearn_estimators,
                "max_depth": 12,
                "min_samples_leaf": 2,
            },
            {
                "n_estimators": self.config.sklearn_estimators,
                "max_depth": None,
                "min_samples_leaf": 4,
            },
        ][: max(1, self.config.sklearn_search_budget)]
        trials: List[Mapping[str, Any]] = []
        for candidate_index, parameters in enumerate(candidates):
            fold_metrics = []
            for fold_index, (training_keys, validation_keys) in enumerate(folds):
                model = SklearnProfileModel(
                    random_state=self.config.seed + candidate_index * 100 + fold_index,
                    n_jobs=1,
                    **parameters,
                )
                model.fit(train_dataset.subset(training_keys))
                fold_metrics.append(
                    evaluate_sklearn_model(
                        model, train_dataset.subset(validation_keys)
                    )
                )
            trials.append(
                {
                    "parameters": dict(parameters),
                    "metrics": average_metrics(fold_metrics),
                }
            )
        selected = min(
            trials,
            key=lambda trial: float(trial["metrics"]["composite_score"]),
        )
        final_model = SklearnProfileModel(
            random_state=self.config.seed,
            n_jobs=1,
            **selected["parameters"],
        ).fit(train_dataset)
        return (
            final_model,
            dict(selected["parameters"]),
            dict(selected["metrics"]),
            trials,
        )

    def _search_torch(
        self,
        train_dataset: LapDataset,
        folds: Sequence[Tuple[Sequence[str], Sequence[str]]],
    ) -> Optional[
        Tuple[
            TorchSequenceModel,
            Mapping[str, Any],
            Mapping[str, float],
            List[Mapping[str, Any]],
        ]
    ]:
        candidates = [
            {"hidden_size": 24, "dropout": 0.10, "learning_rate": 0.003},
            {"hidden_size": 32, "dropout": 0.20, "learning_rate": 0.002},
        ][: max(1, self.config.torch_search_budget)]
        trials: List[Mapping[str, Any]] = []
        for candidate_index, parameters in enumerate(candidates):
            fold_metrics = []
            best_epochs = []
            for fold_index, (training_keys, validation_keys) in enumerate(folds):
                model = TorchSequenceModel(
                    random_state=self.config.seed + candidate_index * 100 + fold_index,
                    max_epochs=self.config.torch_max_epochs,
                    patience=self.config.torch_patience,
                    batch_size=self.config.torch_batch_size,
                    mc_passes=6,
                    **parameters,
                )
                model.fit(
                    train_dataset.subset(training_keys),
                    train_dataset.subset(validation_keys),
                )
                best_epochs.append(model.best_epoch + 1)
                fold_metrics.append(
                    evaluate_torch_model(
                        model, train_dataset.subset(validation_keys)
                    )
                )
            trials.append(
                {
                    "parameters": dict(parameters),
                    "metrics": average_metrics(fold_metrics),
                    "best_epoch_budget": max(1, int(round(float(np.mean(best_epochs))))),
                }
            )
        if not trials:
            return None
        selected = min(
            trials,
            key=lambda trial: float(trial["metrics"]["composite_score"]),
        )
        fixed_epochs = min(
            self.config.torch_max_epochs,
            int(selected["best_epoch_budget"]),
        )
        final_parameters = dict(selected["parameters"])
        final_parameters["fixed_epochs"] = fixed_epochs
        final_model = TorchSequenceModel(
            random_state=self.config.seed,
            max_epochs=fixed_epochs,
            patience=fixed_epochs + 1,
            batch_size=self.config.torch_batch_size,
            mc_passes=8,
            **selected["parameters"],
        ).fit(train_dataset)
        return final_model, final_parameters, dict(selected["metrics"]), trials

    def _holdout_profile(
        self,
        model: Any,
        family: str,
        holdout_dataset: LapDataset,
    ) -> Dict[str, Any]:
        if family == "sklearn":
            profile = model.predict_profiles(holdout_dataset.sample_frame)
            lap_pace = model.predict_lap_pace(holdout_dataset.lap_frame)
        else:
            prediction = model.predict_dataset(holdout_dataset)
            profile = prediction.profiles
            lap_pace = prediction.lap_pace
        expected = np.asarray(profile.expected, dtype=float).reshape(
            len(holdout_dataset.lap_keys),
            holdout_dataset.grid_points,
            len(PROFILE_TARGETS),
        )
        return {
            "schema_version": "1.0",
            "lap_keys": holdout_dataset.lap_keys,
            "progress": np.linspace(0.0, 1.0, holdout_dataset.grid_points).tolist(),
            "targets": list(PROFILE_TARGETS),
            "expected_profiles": expected.tolist(),
            "expected_lap_time_s": np.asarray(
                lap_pace.expected, dtype=float
            ).reshape(-1).tolist(),
        }

    def _experiment_id(self, dataset: LapDataset) -> str:
        payload = {
            "dataset": dataset.fingerprint(),
            "config": asdict(self.config),
            "model_name": self.model_name,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return "exp-{0}".format(digest[:12])

    def _seed_everything(self) -> None:
        random.seed(self.config.seed)
        np.random.seed(self.config.seed)
