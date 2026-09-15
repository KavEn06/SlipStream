from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


class MigrationTests(unittest.TestCase):
    def test_upgrade_check_downgrade_and_reupgrade_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "migration-round-trip.db"
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", "sqlite:///{0}".format(database_path))

            command.upgrade(config, "head")
            engine = create_engine("sqlite:///{0}".format(database_path))
            try:
                schema = inspect(engine)
                self.assertIn("raw_telemetry_samples", schema.get_table_names())
                self.assertIn("result_payload", {
                    column["name"] for column in schema.get_columns("analysis_runs")
                })
                self.assertIn("display_name", {
                    column["name"] for column in schema.get_columns("sessions")
                })
                self.assertIn("ix_raw_session_lap_time", {
                    index["name"] for index in schema.get_indexes("raw_telemetry_samples")
                })
            finally:
                engine.dispose()

            # Alembic's metadata comparison is the migration/model drift check.
            command.check(config)
            command.downgrade(config, "base")

            engine = create_engine("sqlite:///{0}".format(database_path))
            try:
                self.assertEqual(inspect(engine).get_table_names(), ["alembic_version"])
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = create_engine("sqlite:///{0}".format(database_path))
            try:
                self.assertIn("recommendation_ratings", inspect(engine).get_table_names())
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
