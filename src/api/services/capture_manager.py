from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from src.core.config import RAW_DATA_ROOT, REPO_ROOT, build_session_id


class CaptureManager:
    """Singleton that manages one datacollector subprocess at a time."""

    _instance: CaptureManager | None = None

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._session_id: str | None = None
        self._ip: str | None = None
        self._port: int | None = None

    @classmethod
    def get(cls) -> CaptureManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def status(self) -> dict:
        laps_detected = 0
        if self._session_id and self.is_active:
            session_dir = RAW_DATA_ROOT / self._session_id
            if session_dir.exists():
                laps_detected = len(list(session_dir.glob("lap_*.csv")))

        return {
            "is_active": self.is_active,
            "session_id": self._session_id if self.is_active else None,
            "ip": self._ip if self.is_active else None,
            "port": self._port if self.is_active else None,
            "laps_detected": laps_detected,
        }

    def start(
        self,
        ip: str = "127.0.0.1",
        port: int = 5300,
        session_id: str | None = None,
    ) -> dict:
        if self.is_active:
            raise RuntimeError("Capture is already running")

        resolved_id = session_id or build_session_id()
        self._session_id = resolved_id
        self._ip = ip
        self._port = port

        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        cmd = [
            sys.executable,
            str(REPO_ROOT / "src" / "ingest" / "datacollector.py"),
            "--ip", ip,
            "--port", str(port),
            "--session-id", resolved_id,
        ]

        self._process = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=env)
        time.sleep(0.3)
        return self.status

    def stop(self) -> dict:
        if not self.is_active:
            raise RuntimeError("No active capture to stop")

        self._process.send_signal(signal.SIGINT)
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

        final = self.status
        self._process = None
        return {**final, "is_active": False}
