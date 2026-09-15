"""Checksummed artifact storage and database-backed champion registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.telemetry import ModelVersionContract
from src.db import models
from src.db.repositories import ModelRepository
from src.ml.sklearn_model import SklearnProfileModel
from src.ml.torch_model import TorchSequenceModel


MODEL_NAME = "slipstream-pace-profile"


class ArtifactIntegrityError(RuntimeError):
    pass


class ModelArtifactStore:
    def __init__(self, model_root: Path):
        self.model_root = Path(model_root).expanduser().resolve()

    def save(self, model: Any, name: str, version: str) -> Tuple[Path, str, str]:
        model_type = str(getattr(model, "model_type", ""))
        if model_type.startswith("sklearn"):
            extension = ".joblib"
            serializer = self._write_joblib
            artifact_format = "joblib"
        elif model_type.startswith("torch"):
            extension = ".pt"
            serializer = lambda value, path: value.save(path)
            artifact_format = "torch-state-dict"
        else:
            raise ValueError("Unsupported model artifact type: {0}".format(model_type))
        directory = self.model_root / _safe_component(name) / _safe_component(version)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ("model" + extension)
        with tempfile.NamedTemporaryFile(
            prefix=".model-", suffix=extension, dir=str(directory), delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            serializer(model, temporary_path)
            checksum = sha256_file(temporary_path)
            if target.exists():
                existing_checksum = sha256_file(target)
                if existing_checksum != checksum:
                    raise ArtifactIntegrityError(
                        "Immutable artifact already exists with a different checksum: {0}".format(
                            target
                        )
                    )
                temporary_path.unlink()
            else:
                temporary_path.replace(target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        manifest = {
            "name": name,
            "version": version,
            "model_type": model_type,
            "artifact_format": artifact_format,
            "artifact": target.name,
            "sha256": checksum,
        }
        manifest_path = directory / "manifest.json"
        encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != encoded:
            raise ArtifactIntegrityError(
                "Immutable artifact manifest already exists with different content: {0}".format(
                    manifest_path
                )
            )
        if not manifest_path.exists():
            manifest_path.write_text(encoded, encoding="utf-8")
        return target, checksum, artifact_format

    @staticmethod
    def _write_joblib(model: Any, path: Path) -> None:
        try:
            import joblib
        except ImportError as exc:
            raise ImportError(
                "joblib is required to serialize scikit-learn model artifacts"
            ) from exc
        joblib.dump(model, str(path), compress=3)


class ModelRegistry:
    def __init__(
        self,
        database_session: Session,
        model_root: Path,
        model_name: str = MODEL_NAME,
    ):
        self.database_session = database_session
        self.model_root = Path(model_root)
        self.model_name = model_name
        self.repository = ModelRepository(database_session)
        self.artifacts = ModelArtifactStore(model_root)

    def register(
        self,
        model: Any,
        version: str,
        metrics_by_split: Mapping[str, Mapping[str, float]],
        dataset_metadata: Mapping[str, Any],
        holdout_profile: Optional[Mapping[str, Any]] = None,
    ) -> models.ModelVersion:
        artifact_path, checksum, artifact_format = self.artifacts.save(
            model, self.model_name, version
        )
        metadata = dict(model.metadata())
        metadata.update(
            {
                "artifact_format": artifact_format,
                "dataset": dict(dataset_metadata),
            }
        )
        row = self.repository.upsert_version(
            ModelVersionContract(
                name=self.model_name,
                version=version,
                model_type=str(model.model_type),
                artifact_uri=artifact_path.as_uri(),
                source_revisions=dict(dataset_metadata.get("source_revisions", {})),
                compatibility={
                    "python": ">=3.9",
                    "device": "cpu",
                    "grid_points": dataset_metadata.get("grid_points"),
                    "section_count": dataset_metadata.get("section_count"),
                    "simulator_neutral": True,
                },
                feature_definition={
                    "profile_targets": ["throttle", "brake", "steering", "speed_mps"],
                    "track_car_calibration": True,
                    "whole_lap_grouping": True,
                },
            ),
            status="challenger",
            checksum=checksum,
            metadata=metadata,
        )
        for split, metrics in metrics_by_split.items():
            for name, value in metrics.items():
                self.repository.upsert_metric(
                    row.id,
                    str(split),
                    str(name),
                    float(value),
                    metadata={
                        "lower_is_better": not (
                            name.endswith("_accuracy")
                            or name.endswith("_coverage")
                        )
                    },
                )
        if holdout_profile is not None:
            self.repository.upsert_prediction(
                model_version_id=row.id,
                profile_key="{0}:holdout".format(version),
                values=dict(holdout_profile),
                metadata={
                    "immutable_holdout": True,
                    "purpose": "offline-evaluation",
                },
            )
        return row

    def promote(self, model_version_id: int) -> models.ModelVersion:
        selected = self.database_session.get(models.ModelVersion, model_version_id)
        if selected is None or selected.name != self.model_name:
            raise KeyError("Unknown model version for registry: {0}".format(model_version_id))
        existing = self.database_session.scalars(
            select(models.ModelVersion).where(models.ModelVersion.name == self.model_name)
        ).all()
        for row in existing:
            row.status = "champion" if row.id == selected.id else "challenger"
        self.database_session.flush()
        return selected

    def champion_row(self) -> Optional[models.ModelVersion]:
        return self.database_session.scalar(
            select(models.ModelVersion)
            .where(
                models.ModelVersion.name == self.model_name,
                models.ModelVersion.status == "champion",
            )
            .order_by(models.ModelVersion.created_at.desc(), models.ModelVersion.id.desc())
            .limit(1)
        )

    def load_champion(self) -> Any:
        row = self.champion_row()
        if row is None:
            raise LookupError("No champion is registered for {0}".format(self.model_name))
        return self.load_version(row)

    def load_version(self, row: models.ModelVersion) -> Any:
        """Load and checksum-verify a specific registered model version."""

        if row.name != self.model_name:
            raise ArtifactIntegrityError(
                "Model version does not belong to registry {0}".format(self.model_name)
            )
        if not row.artifact_uri or not row.checksum:
            raise ArtifactIntegrityError("Model artifact metadata is incomplete")
        path = _artifact_path(row.artifact_uri)
        if not path.is_file():
            raise ArtifactIntegrityError("Model artifact does not exist: {0}".format(path))
        checksum = sha256_file(path)
        if checksum != row.checksum:
            raise ArtifactIntegrityError(
                "Model checksum mismatch for {0}".format(path)
            )
        artifact_format = dict(row.metadata_json or {}).get("artifact_format")
        if artifact_format == "joblib":
            try:
                import joblib
            except ImportError as exc:
                raise ImportError(
                    "joblib is required to load the scikit-learn champion"
                ) from exc
            model = joblib.load(str(path))
            if not isinstance(model, SklearnProfileModel):
                raise ArtifactIntegrityError("Model joblib has an unexpected model class")
            return model
        if artifact_format == "torch-state-dict":
            return TorchSequenceModel.load(path)
        raise ArtifactIntegrityError(
            "Unsupported champion artifact format: {0}".format(artifact_format)
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip(".-")
    if not cleaned:
        raise ValueError("Artifact path component cannot be empty")
    return cleaned


def _artifact_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        raise ArtifactIntegrityError("Only local file artifacts are supported")
    raw_path = unquote(parsed.path) if parsed.scheme == "file" else uri
    return Path(raw_path).expanduser().resolve()
