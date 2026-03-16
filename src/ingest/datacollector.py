from __future__ import annotations

import argparse
import csv
import json
import socket
import struct
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.config import DEFAULT_LISTEN_IP, DEFAULT_LISTEN_PORT, DEFAULT_SIM_NAME, get_session_paths
from src.schemas import RAW_LAP_COLUMNS, SCHEMA_VERSION, SessionMetadata
from src.tracks import get_track_metadata


class ForzaTelemetryDecoder:
    """Decode the Forza Data Out packet into a stable raw lap schema."""

    format_string = (
        "<iI"
        "4f"
        "3f"
        "3f"
        "3f"
        "3f"
        "3f"
        "4f"
        "4f"
        "4i"
        "4f"
        "4f"
        "4f"
        "4f"
        "4f"
        "i"
        "i"
        "i"
        "i"
        "i"
        "3f"
        "f"
        "f"
        "f"
        "4f"
        "f"
        "f"
        "f"
        "f"
        "f"
        "f"
        "f"
        "H"
        "B"
        "B"
        "B"
        "B"
        "B"
        "B"
        "b"
        "b"
        "b"
        "4f"
        "i"
    )
    packet_size = struct.calcsize(format_string)

    field_map = {
        "IsRaceOn": 0,
        "TimestampMS": 1,
        "EngineMaxRpm": 2,
        "EngineIdleRpm": 3,
        "CurrentEngineRpm": 4,
        "CarOrdinal": 53,
        "PositionX": 58,
        "PositionY": 59,
        "PositionZ": 60,
        "Speed": 61,
        "Power": 62,
        "Torque": 63,
        "Boost": 68,
        "DistanceTraveled": 70,
        "BestLap": 71,
        "LastLap": 72,
        "CurrentLap": 73,
        "CurrentRaceTime": 74,
        "LapNumber": 75,
        "Accel": 77,
        "Brake": 78,
        "Clutch": 79,
        "HandBrake": 80,
        "Gear": 81,
        "Steer": 82,
        "TrackOrdinal": 89,
    }

    def decode_packet(self, data: bytes) -> dict[str, float | int]:
        if len(data) < self.packet_size:
            raise ValueError(f"Packet too small: expected {self.packet_size} bytes, got {len(data)}")

        unpacked_data = struct.unpack(self.format_string, data[: self.packet_size])
        telemetry = {field: unpacked_data[index] for field, index in self.field_map.items()}
        telemetry["LapNumber"] = int(telemetry["LapNumber"])
        telemetry["CarOrdinal"] = int(telemetry["CarOrdinal"])
        telemetry["TrackOrdinal"] = int(telemetry["TrackOrdinal"])
        telemetry["Gear"] = int(telemetry["Gear"])
        telemetry["IsRaceOn"] = int(telemetry["IsRaceOn"])
        telemetry["TimestampMS"] = int(telemetry["TimestampMS"])
        return telemetry


class datacollector:
    def __init__(self, ip: str = DEFAULT_LISTEN_IP, port: int = DEFAULT_LISTEN_PORT, session_id: str | None = None):
        self.ip = ip
        self.port = port
        self.decoder = ForzaTelemetryDecoder()
        self.session_paths = get_session_paths(session_id)
        self.output_dir = str(self.session_paths.raw_dir)
        self.session_paths.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session_paths.processed_dir.mkdir(parents=True, exist_ok=True)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))

        self.current_lap_number = -1
        self.output_file = None
        self.csv_writer = None
        self.completed_laps: set[int] = set()
        self.row_count = 0

        self.car_ordinal: int | None = None
        self.track_ordinal: int | None = None
        self.created_at_utc = datetime.now(timezone.utc).isoformat()
        self.metadata = SessionMetadata(
            session_id=self.session_paths.session_id,
            schema_version=SCHEMA_VERSION,
            sim=DEFAULT_SIM_NAME,
            created_at_utc=self.created_at_utc,
            capture_ip=self.ip,
            capture_port=self.port,
            car_ordinal=None,
            track_ordinal=None,
            track_circuit=None,
            track_layout=None,
            track_location=None,
            track_length_m=None,
            total_laps=0,
            notes="",
        )

    def process_packet(self, data: bytes) -> None:
        telemetry = self.decoder.decode_packet(data)
        self.record_telemetry(telemetry)

    def record_telemetry(self, telemetry: dict[str, float | int]) -> None:
        if telemetry["IsRaceOn"] == 0:
            return

        self._update_metadata_from_telemetry(telemetry)
        lap_number = int(telemetry["LapNumber"])

        if self.current_lap_number == -1:
            self.start_new_lap_file(lap_number)
        elif lap_number != self.current_lap_number:
            self.finalize_current_lap()
            self.start_new_lap_file(lap_number)

        if self.csv_writer is not None:
            self.csv_writer.writerow([telemetry[column] for column in RAW_LAP_COLUMNS])
            self.row_count += 1

    def start_new_lap_file(self, lap_num: int) -> None:
        self.finalize_current_lap()
        self.current_lap_number = lap_num

        filename = self.session_paths.raw_dir / f"lap_{lap_num:03d}.csv"
        print(f"Recording lap {lap_num} to {filename}")
        self.output_file = filename.open("w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.output_file)
        self.csv_writer.writerow(RAW_LAP_COLUMNS)

    def finalize_current_lap(self) -> None:
        if self.output_file is None:
            return

        self.output_file.close()
        self.output_file = None
        self.csv_writer = None

        if self.current_lap_number >= 0:
            self.completed_laps.add(self.current_lap_number)

    def _update_metadata_from_telemetry(self, telemetry: dict[str, float | int]) -> None:
        self.car_ordinal = int(telemetry["CarOrdinal"])
        self.track_ordinal = int(telemetry["TrackOrdinal"])
        track_metadata = get_track_metadata(self.track_ordinal)

        self.metadata = replace(
            self.metadata,
            car_ordinal=self.car_ordinal,
            track_ordinal=self.track_ordinal,
            track_circuit=track_metadata.get("track_circuit"),
            track_layout=track_metadata.get("track_layout"),
            track_location=track_metadata.get("track_location"),
            track_length_m=track_metadata.get("track_length_m"),
            total_laps=len(self.completed_laps) + (1 if self.current_lap_number >= 0 else 0),
        )

    def write_metadata(self) -> None:
        current_lap_total = len(self.completed_laps) + (1 if self.output_file is not None else 0)
        metadata = replace(self.metadata, total_laps=current_lap_total)

        with self.session_paths.raw_metadata_path.open("w", encoding="utf-8") as json_file:
            json.dump(metadata.to_dict(), json_file, indent=2)

    def end_collection(self) -> None:
        self.finalize_current_lap()
        self.write_metadata()
        self.current_lap_number = -1

    def run(self) -> None:
        print(f"Listening for Forza telemetry on {self.ip}:{self.port}...")
        try:
            while True:
                data, _ = self.sock.recvfrom(1024)
                if len(data) >= self.decoder.packet_size:
                    self.process_packet(data)
        except KeyboardInterrupt:
            self.end_collection()
            print("\nStopped logging.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Forza telemetry and persist raw laps.")
    parser.add_argument("--ip", default=DEFAULT_LISTEN_IP, help="IP address to bind to.")
    parser.add_argument("--port", default=DEFAULT_LISTEN_PORT, type=int, help="UDP port to bind to.")
    parser.add_argument("--session-id", default=None, help="Optional session identifier override.")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    logger = datacollector(ip=args.ip, port=args.port, session_id=args.session_id)
    logger.run()