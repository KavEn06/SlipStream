from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.core.config import PROCESSED_DATA_ROOT, RAW_DATA_ROOT
from src.ingest.raceplots import plot
from src.processing.distance import build_processed_lap_file
from src.core.schemas import RAW_LAP_COLUMNS


def discover_raw_csvs() -> list[Path]:
    return sorted(path for path in RAW_DATA_ROOT.rglob("*.csv") if path.is_file())


def is_slipstream_raw_csv(path: Path) -> bool:
    try:
        columns = list(pd.read_csv(path, nrows=0).columns)
    except Exception:
        return False
    return set(RAW_LAP_COLUMNS).issubset(columns)


def choose_raw_file(paths: list[Path]) -> Path:
    print("Available raw CSV files:\n")
    for index, path in enumerate(paths, start=1):
        relative_path = path.relative_to(RAW_DATA_ROOT)
        compatibility = "compatible" if is_slipstream_raw_csv(path) else "non-SlipStream schema"
        print(f"{index}. {relative_path} [{compatibility}]")

    while True:
        choice = input("\nChoose a file number: ").strip()
        if not choice.isdigit():
            print("Enter a valid number.")
            continue

        selected_index = int(choice)
        if 1 <= selected_index <= len(paths):
            return paths[selected_index - 1]

        print("Choice out of range.")


def build_processed_output_path(raw_path: Path) -> Path:
    try:
        relative_path = raw_path.relative_to(RAW_DATA_ROOT)
    except ValueError:
        return PROCESSED_DATA_ROOT / raw_path.name
    return PROCESSED_DATA_ROOT / relative_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Choose a raw telemetry CSV, process it, and open debug plots for review."
    )
    parser.add_argument(
        "--raw-file",
        default=None,
        help="Optional raw CSV path. If omitted, an interactive chooser is shown.",
    )
    args = parser.parse_args()

    if args.raw_file:
        raw_path = Path(args.raw_file).expanduser().resolve()
    else:
        raw_files = discover_raw_csvs()
        if not raw_files:
            raise FileNotFoundError(f"No raw CSV files found under {RAW_DATA_ROOT}")
        raw_path = choose_raw_file(raw_files)

    if not is_slipstream_raw_csv(raw_path):
        raise ValueError(
            f"{raw_path} does not match SlipStream's raw schema. "
            "Use a CSV produced by datacollector.py or add an import/adapter step first."
        )

    print(f"\nSelected raw file: {raw_path}")
    print("Opening raw telemetry plot...")
    plot(str(raw_path))

    processed_path = build_processed_output_path(raw_path)
    session_id = raw_path.parent.name
    print(f"\nProcessing lap to: {processed_path}")
    build_processed_lap_file(raw_path, processed_path, session_id=session_id)

    print("Opening processed telemetry plot...")
    plot(str(processed_path))

    print(f"\nProcessed lap written to {processed_path}")


if __name__ == "__main__":
    main()
