import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CaptureStatus } from "../types";

export const DEFAULT_CAPTURE_IP = "127.0.0.1";
export const DEFAULT_CAPTURE_PORT = "5300";

interface UseCaptureControllerOptions {
  pollIntervalMs?: number;
  defaultIp?: string;
  defaultPort?: string;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Capture request failed";
}

function normalizeCaptureStatus(status: CaptureStatus): CaptureStatus {
  if (status.is_active) {
    return status;
  }

  return {
    ...status,
    session_id: null,
    ip: null,
    port: null,
    laps_detected: 0,
  };
}

export function useCaptureController({
  pollIntervalMs = 2000,
  defaultIp = DEFAULT_CAPTURE_IP,
  defaultPort = DEFAULT_CAPTURE_PORT,
}: UseCaptureControllerOptions = {}) {
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  const [ip, setIp] = useState(defaultIp);
  const [port, setPort] = useState(defaultPort);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const nextStatus = normalizeCaptureStatus(await api.getCaptureStatus());
        if (cancelled) return;
        setStatus(nextStatus);
        setError(null);
      } catch {
        if (!cancelled) {
          setError("Unable to load capture status");
        }
      }
    };

    void poll();
    const id = window.setInterval(poll, pollIntervalMs);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [pollIntervalMs]);

  const refresh = async () => {
    try {
      const nextStatus = normalizeCaptureStatus(await api.getCaptureStatus());
      setStatus(nextStatus);
      setError(null);
      return nextStatus;
    } catch (err) {
      setError(getErrorMessage(err));
      return null;
    }
  };

  const startCapture = async () => {
    setBusy(true);
    try {
      const nextIp = ip.trim() || defaultIp;
      const nextPort = port.trim() || defaultPort;
      const result = normalizeCaptureStatus(
        await api.startCapture({ ip: nextIp, port: parseInt(nextPort, 10) }),
      );
      setIp(nextIp);
      setPort(nextPort);
      setStatus(result);
      setError(null);
      return result;
    } catch (err) {
      const message = getErrorMessage(err);
      setError(message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const stopCapture = async () => {
    setBusy(true);
    try {
      const result = normalizeCaptureStatus(await api.stopCapture());
      setStatus(result);
      setError(null);
      return result;
    } catch (err) {
      const message = getErrorMessage(err);
      setError(message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  return {
    status,
    ip,
    port,
    busy,
    error,
    setIp,
    setPort,
    refresh,
    startCapture,
    stopCapture,
  };
}
