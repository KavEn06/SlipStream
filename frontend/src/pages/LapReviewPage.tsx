import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { LapData } from "../types";
import { LapChart } from "../components/LapChart";

const CHART_COLORS = {
  speed: "#f1f1f2",
  throttle: "#d14b4b",
  brake: "#ff6b6b",
  steering: "#8b8b92",
};

function formatLapTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(3);
  return mins > 0 ? `${mins}:${secs.padStart(6, "0")}` : `${secs}s`;
}

export function LapReviewPage() {
  const { sessionId, lapNumber } = useParams<{
    sessionId: string;
    lapNumber: string;
  }>();
  const [dataType, setDataType] = useState<"processed" | "raw">("processed");
  const [lapData, setLapData] = useState<LapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId || !lapNumber) return;
    setLoading(true);
    setError(null);

    api
      .getLap(sessionId, parseInt(lapNumber), dataType)
      .then(setLapData)
      .catch((err) => {
        if (dataType === "processed") {
          api
            .getLap(sessionId, parseInt(lapNumber), "raw")
            .then((data) => {
              setLapData(data);
              setDataType("raw");
            })
            .catch(() => setError(err.message));
        } else {
          setError(err.message);
        }
      })
      .finally(() => setLoading(false));
  }, [sessionId, lapNumber, dataType]);

  if (!sessionId || !lapNumber) return null;

  const isProcessed = dataType === "processed";
  const speedCol = isProcessed ? "SpeedKph" : "Speed";
  const throttleCol = isProcessed ? "Throttle" : "Accel";
  const brakeCol = "Brake";
  const steeringCol = isProcessed ? "Steering" : "Steer";
  const xCol = isProcessed ? "NormalizedDistance" : undefined;

  const first = lapData?.records?.[0];
  const lapTimeS = first?.LapTimeS as number | undefined;
  const lapIsValid = first?.LapIsValid as number | undefined;

  return (
    <div className="max-w-6xl space-y-8">
      <div>
        <Link
          to={`/sessions/${sessionId}`}
          className="text-sm text-text-muted transition-colors hover:text-text-secondary"
        >
          &larr; {sessionId}
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <h2 className="text-3xl font-semibold tracking-tight">Lap {lapNumber}</h2>
          {lapTimeS !== undefined && (
            <span className="font-mono text-lg text-text-secondary">
              {formatLapTime(lapTimeS)}
            </span>
          )}
          {lapIsValid !== undefined && (
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                lapIsValid
                  ? "bg-success/15 text-success"
                  : "bg-danger/15 text-danger"
              }`}
            >
              {lapIsValid ? "Valid" : "Invalid"}
            </span>
          )}
        </div>
      </div>

      <div className="flex w-fit gap-1 rounded-full border border-border/70 bg-surface-1/85 p-1">
        {(["processed", "raw"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setDataType(t)}
            className={`rounded-full px-4 py-1.5 text-sm capitalize transition-colors cursor-pointer ${
              dataType === t
                ? "bg-surface-2 text-accent font-medium"
                : "text-text-muted hover:bg-surface-2 hover:text-text-secondary"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-text-muted">Loading lap data...</p>
      ) : error ? (
        <p className="text-danger text-sm">{error}</p>
      ) : lapData ? (
        <div className="space-y-4">
          <LapChart
            data={lapData.records}
            xKey={xCol}
            yKey={speedCol}
            label={isProcessed ? "Speed (km/h)" : "Speed (m/s)"}
            color={CHART_COLORS.speed}
            height={240}
          />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <LapChart
              data={lapData.records}
              xKey={xCol}
              yKey={throttleCol}
              label={isProcessed ? "Throttle (0-1)" : "Throttle (0-255)"}
              color={CHART_COLORS.throttle}
            />
            <LapChart
              data={lapData.records}
              xKey={xCol}
              yKey={brakeCol}
              label={isProcessed ? "Brake (0-1)" : "Brake (0-255)"}
              color={CHART_COLORS.brake}
            />
          </div>
          <LapChart
            data={lapData.records}
            xKey={xCol}
            yKey={steeringCol}
            label="Steering"
            color={CHART_COLORS.steering}
          />
        </div>
      ) : null}
    </div>
  );
}
