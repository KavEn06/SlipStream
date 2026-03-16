from __future__ import annotations

import sys

import matplotlib.pyplot as plt
import pandas as pd


def _time_axis(df: pd.DataFrame) -> pd.Series:
    if "ElapsedTimeS" in df.columns:
        return df["ElapsedTimeS"]
    if "TimestampMS" in df.columns:
        return (df["TimestampMS"] - df["TimestampMS"].iloc[0]) / 1000.0
    raise ValueError("CSV must contain either ElapsedTimeS or TimestampMS")


def plot(file_name: str) -> None:
    df = pd.read_csv(file_name)
    time_s = _time_axis(df)

    speed_column = "SpeedKph" if "SpeedKph" in df.columns else "Speed"
    throttle_column = "Throttle" if "Throttle" in df.columns else "Accel"
    brake_column = "Brake"
    steering_column = "Steering" if "Steering" in df.columns else "Steer"

    fig, axs = plt.subplots(4, 1, figsize=(12, 8), sharex=True)

    axs[0].plot(time_s, df[speed_column])
    axs[0].set_ylabel(speed_column)

    axs[1].plot(time_s, df[throttle_column])
    axs[1].set_ylabel(throttle_column)

    axs[2].plot(time_s, df[brake_column])
    axs[2].set_ylabel(brake_column)

    axs[3].plot(time_s, df[steering_column])
    axs[3].set_ylabel(steering_column)
    axs[3].set_xlabel("Time (s)")

    plt.suptitle("SlipStream Telemetry Debug Plot")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/ingest/raceplots.py path/to/lap.csv")
        sys.exit(1)

    plot(sys.argv[1])