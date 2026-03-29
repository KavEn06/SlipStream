from __future__ import annotations

import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from src.core.config import SessionPaths
from src.core.schemas import LAP_CLOSE_REASON_CAPTURE_END, LAP_CLOSE_REASON_LAP_ROLLOVER
from src.ingest.datacollector import ForzaTelemetryDecoder, datacollector


class IngestTests(unittest.TestCase):
    def test_decoder_extracts_schema_fields(self) -> None:
        decoder = ForzaTelemetryDecoder()
        values = [0] * 90
        values[0] = 1
        values[1] = 1234
        values[2] = 8000.0
        values[3] = 900.0
        values[4] = 4500.0
        values[53] = 12
        values[58] = 1.5
        values[59] = 0.0
        values[60] = 2.5
        values[61] = 42.0
        values[62] = 180.0
        values[63] = 220.0
        values[68] = 0.2
        values[70] = 100.0
        values[71] = 85.0
        values[72] = 86.0
        values[73] = 1.2
        values[74] = 50.0
        values[75] = 3
        values[77] = 200
        values[78] = 0
        values[79] = 0
        values[80] = 0
        values[81] = 4
        values[82] = -10
        values[89] = 110

        packet = struct.pack(decoder.format_string, *values)
        telemetry = decoder.decode_packet(packet)

        self.assertEqual(telemetry["TimestampMS"], 1234)
        self.assertEqual(telemetry["LapNumber"], 3)
        self.assertEqual(telemetry["Gear"], 4)
        self.assertEqual(telemetry["TrackOrdinal"], 110)
        self.assertAlmostEqual(float(telemetry["PositionX"]), 1.5)
        self.assertAlmostEqual(float(telemetry["Speed"]), 42.0)

    def test_collector_writes_laps_enriched_metadata_and_lap_index(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        collector = datacollector(ip="127.0.0.1", port=0, session_id="session_test_ingest", bind_socket=False)
        collector.session_paths = SessionPaths(
            session_id="session_test_ingest",
            raw_dir=temp_root / "raw" / "session_test_ingest",
            processed_dir=temp_root / "processed" / "session_test_ingest",
            raw_metadata_path=temp_root / "raw" / "session_test_ingest" / "metadata.json",
            processed_metadata_path=temp_root / "processed" / "session_test_ingest" / "metadata.json",
        )
        collector.session_paths.raw_dir.mkdir(parents=True, exist_ok=True)
        collector.session_paths.processed_dir.mkdir(parents=True, exist_ok=True)
        collector.output_dir = str(collector.session_paths.raw_dir)

        try:
            packet_lap_1 = self._build_packet(timestamp_ms=1000, lap_number=1, position_x=0.0, speed=30.0, current_lap=0.2)
            packet_lap_1_b = self._build_packet(timestamp_ms=1050, lap_number=1, position_x=2.0, speed=31.0, current_lap=0.25)
            packet_lap_2 = self._build_packet(timestamp_ms=1100, lap_number=2, position_x=4.0, speed=28.0, current_lap=0.05)

            collector.process_packet(packet_lap_1)
            collector.process_packet(packet_lap_1_b)
            collector.process_packet(packet_lap_2)
            collector.end_collection()

            lap_one = collector.session_paths.raw_dir / "lap_001.csv"
            lap_two = collector.session_paths.raw_dir / "lap_002.csv"
            metadata_path = collector.session_paths.raw_metadata_path

            self.assertTrue(lap_one.exists())
            self.assertTrue(lap_two.exists())

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["total_laps"], 2)
            self.assertEqual(metadata["track_ordinal"], 110)
            self.assertEqual(metadata["track_circuit"], "Circuit de Barcelona-Catalunya")
            self.assertEqual(metadata["lap_index"]["1"]["close_reason"], LAP_CLOSE_REASON_LAP_ROLLOVER)
            self.assertEqual(metadata["lap_index"]["1"]["first_timestamp_ms"], 1000)
            self.assertEqual(metadata["lap_index"]["1"]["last_timestamp_ms"], 1050)
            self.assertEqual(metadata["lap_index"]["2"]["close_reason"], LAP_CLOSE_REASON_CAPTURE_END)
            self.assertEqual(metadata["lap_index"]["2"]["first_timestamp_ms"], 1100)
            self.assertEqual(metadata["lap_index"]["2"]["last_timestamp_ms"], 1100)
        finally:
            collector.sock.close()
            shutil.rmtree(temp_root)

    @staticmethod
    def _build_packet(
        timestamp_ms: int,
        lap_number: int,
        position_x: float,
        speed: float,
        current_lap: float,
    ) -> bytes:
        decoder = ForzaTelemetryDecoder()
        values = [0] * 90
        values[0] = 1
        values[1] = timestamp_ms
        values[2] = 8000.0
        values[3] = 900.0
        values[4] = 4200.0
        values[53] = 12
        values[58] = position_x
        values[59] = 0.0
        values[60] = position_x / 2.0
        values[61] = speed
        values[62] = 150.0
        values[63] = 220.0
        values[68] = 0.2
        values[70] = max(position_x, 0.0)
        values[71] = 85.0
        values[72] = 86.0
        values[73] = current_lap
        values[74] = timestamp_ms / 1000.0
        values[75] = lap_number
        values[77] = 180
        values[78] = 0
        values[79] = 0
        values[80] = 0
        values[81] = 3
        values[82] = 0
        values[89] = 110
        return struct.pack(decoder.format_string, *values)


if __name__ == "__main__":
    unittest.main()
