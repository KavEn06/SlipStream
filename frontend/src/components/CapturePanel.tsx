import { useState } from "react";
import { useCaptureController } from "../hooks/useCaptureController";

interface Props {
  onCaptureChange?: () => void;
}

export function CapturePanel({ onCaptureChange }: Props) {
  const [expanded, setExpanded] = useState(false);
  const capture = useCaptureController();
  const isActive = capture.status?.is_active ?? false;

  const handleAction = async () => {
    const result = isActive
      ? await capture.stopCapture()
      : await capture.startCapture();
    if (result) {
      onCaptureChange?.();
    }
  };

  return (
    <div className="rounded-3xl border border-white/5 bg-white/[0.02]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-4 text-left cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div
            className={`w-2.5 h-2.5 rounded-full ${
              isActive ? "bg-success animate-pulse" : "bg-text-muted"
            }`}
          />
          <span className="text-sm font-medium">Capture</span>
          {isActive && capture.status && (
            <span className="text-xs text-text-muted">
              {capture.status.laps_detected} laps &middot; {capture.status.session_id}
            </span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-text-muted transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-white/5 px-5 pb-5 pt-4">
          {!isActive && (
            <div className="flex gap-3">
              <div>
                <label className="block text-xs text-text-muted mb-1">
                  IP Address
                </label>
                <input
                  type="text"
                  value={capture.ip}
                  onChange={(e) => capture.setIp(e.target.value)}
                  className="w-36 rounded-full border border-white/6 bg-black/30 px-3 py-2 text-sm focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1">
                  Port
                </label>
                <input
                  type="text"
                  value={capture.port}
                  onChange={(e) => capture.setPort(e.target.value)}
                  className="w-24 rounded-full border border-white/6 bg-black/30 px-3 py-2 text-sm focus:border-accent focus:outline-none"
                />
              </div>
            </div>
          )}
          <button
            onClick={handleAction}
            disabled={capture.busy}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-colors cursor-pointer ${
              isActive
                ? "bg-danger/12 text-danger hover:bg-danger/18"
                : "bg-accent/12 text-accent hover:bg-accent/18"
            } disabled:opacity-50`}
          >
            {capture.busy ? "..." : isActive ? "Stop Capture" : "Start Capture"}
          </button>
          {capture.error && (
            <p className="text-sm text-danger">{capture.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
