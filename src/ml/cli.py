"""Command-line entrypoint for offline SlipStream ML experiments."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Optional, Sequence

from src.core.config import get_settings
from src.db.session import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from src.ml.dataset import TelemetryDatasetBuilder
from src.ml.experiment import ExperimentConfig, OfflineExperimentRunner
from src.ml.registry import ModelRegistry


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Train and inspect leakage-safe telemetry ML models."
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--model-root", type=Path, default=settings.model_root)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser(
        "dataset-summary", help="Report effective laps and resampled rows."
    )
    _add_dataset_arguments(summary)

    train = subparsers.add_parser(
        "train", help="Run grouped offline search and register a champion."
    )
    _add_dataset_arguments(train)
    train.add_argument("--seed", type=int, default=1729)
    train.add_argument("--holdout-fraction", type=float, default=0.20)
    train.add_argument("--cv-folds", type=int, default=3)
    train.add_argument("--sklearn-budget", type=int, default=3)
    train.add_argument("--torch-budget", type=int, default=2)
    train.add_argument("--torch-epochs", type=int, default=20)
    train.add_argument("--no-torch", action="store_true")

    subparsers.add_parser(
        "champion", help="Verify and display the registered champion artifact."
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    engine = create_database_engine(args.database_url)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as database_session:
            if args.command == "champion":
                registry = ModelRegistry(database_session, args.model_root)
                row = registry.champion_row()
                if row is None:
                    raise LookupError("No champion model is registered")
                model = registry.load_champion()
                payload = {
                    "id": row.id,
                    "name": row.name,
                    "version": row.version,
                    "model_type": row.model_type,
                    "artifact_uri": row.artifact_uri,
                    "checksum": row.checksum,
                    "metadata": model.metadata(),
                }
            else:
                builder = TelemetryDatasetBuilder(
                    grid_points=args.grid_points,
                    section_count=args.sections,
                )
                dataset = builder.from_database(database_session)
                if args.command == "dataset-summary":
                    payload = {
                        "fingerprint": dataset.fingerprint(),
                        "effective_laps": dataset.effective_lap_count,
                        "resampled_rows": dataset.sample_row_count,
                        "source_revisions": dict(dataset.source_revisions),
                    }
                else:
                    config = ExperimentConfig(
                        seed=args.seed,
                        holdout_fraction=args.holdout_fraction,
                        cv_folds=args.cv_folds,
                        sklearn_search_budget=args.sklearn_budget,
                        torch_search_budget=args.torch_budget,
                        include_torch=not args.no_torch,
                        torch_max_epochs=args.torch_epochs,
                    )
                    result = OfflineExperimentRunner(
                        args.model_root, config=config
                    ).run(dataset, database_session)
                    payload = asdict(result)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    finally:
        engine.dispose()


def _add_dataset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--grid-points", type=int, default=64)
    parser.add_argument("--sections", type=int, default=8)


if __name__ == "__main__":
    raise SystemExit(main())
