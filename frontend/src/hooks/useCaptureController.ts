import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CaptureStatus } from "../types";

interface UseCaptureControllerOptions {
  pollIntervalMs?: number;
  defaultIp?: string;
  defaultPort?: string;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Capture request failed";
}

export function useCaptureController({
  pollIntervalMs = 2000,
  defaultIp = "127.0.0.1",
  defaultPort = "5300",
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
        const nextStatus = await api.getCaptureStatus();
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
      const nextStatus = await api.getCaptureStatus();
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
      const result = await api.startCapture({ ip, port: parseInt(port, 10) });
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
      const result = await api.stopCapture();
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
