import pandas as pd
import matplotlib.pyplot as plt
import sys

def plot(fileName): 
    df = pd.read_csv(fileName)

    time = df['Time'] / 1000

    fig, axs = plt.subplots(4, 1, figsize=(12, 8), sharex=True)

    axs[0].plot(time, df["Speed"])
    axs[0].set_ylabel("Speed")

    axs[1].plot(time, df["Accel"])
    axs[1].set_ylabel("Throttle")

    axs[2].plot(time, df["Brake"])
    axs[2].set_ylabel("Brake")

    axs[3].plot(time, df["Steer"])
    axs[3].set_ylabel("Steer")
    axs[3].set_xlabel("Time (s)")

    plt.suptitle("Forza Telemetry Debug Plot")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_plots.py path/to/lap.csv")
        sys.exit(1)

    plot(sys.argv[1])

#to run: python src/ingest/raceplots.py data/raw/session_001/lap_01.csv