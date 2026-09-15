from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.core.config import get_settings
from src.core.telemetry import DataSourceContract, LapContract, SessionContract
from src.db.repositories import CatalogRepository, DataSourceRepository, SessionRepository, TelemetryRepository
from src.db.session import create_database_engine, create_session_factory, session_scope
from src.ingest.forza import map_forza_row


class ForzaLapPersister:
    """Persist one closed live lap in its own short transaction."""

    def __init__(self, database_url: str = ""):
        settings = get_settings()
        self.engine = create_database_engine(database_url or settings.database_url)
        self.factory = create_session_factory(self.engine)
        self.batch_size = settings.import_batch_size

    def persist_completed_lap(
        self,
        session_external_id: str,
        metadata: Mapping[str, Any],
        lap_number: int,
        rows: Sequence[Mapping[str, Any]],
        close_reason: str,
    ) -> None:
        if not rows:
            return
        with session_scope(self.factory) as database_session:
            sources = DataSourceRepository(database_session)
            catalog = CatalogRepository(database_session)
            sessions = SessionRepository(database_session)
            telemetry = TelemetryRepository(database_session)
            source = sources.upsert(
                DataSourceContract(
                    key="live:forza-data-out",
                    kind="live_udp",
                    simulator="Forza Motorsport",
                    provider="Forza Data Out",
                    provenance={"capture": "udp"},
                )
            )
            track_id = None
            track_ordinal = metadata.get("track_ordinal")
            if track_ordinal is not None:
                track = catalog.upsert_track(
                    identity_key="forza:track:{0}".format(track_ordinal),
                    simulator="Forza Motorsport",
                    external_id=str(track_ordinal),
                    circuit=str(metadata.get("track_circuit") or "Unknown track"),
                    layout=metadata.get("track_layout"),
                    location=metadata.get("track_location"),
                    length_m=metadata.get("track_length_m"),
                )
                track_id = track.id
            car_id = None
            car_ordinal = metadata.get("car_ordinal")
            if car_ordinal is not None:
                car = catalog.upsert_car(
                    identity_key="forza:car:{0}".format(car_ordinal),
                    simulator="Forza Motorsport",
                    external_id=str(car_ordinal),
                    model="Forza car {0}".format(car_ordinal),
                )
                car_id = car.id
            stored_session = sessions.upsert_session(
                source.id,
                SessionContract(
                    external_id=session_external_id,
                    simulator="Forza Motorsport",
                    provenance={"live_capture_metadata": dict(metadata)},
                ),
                track_id=track_id,
                car_id=car_id,
            )
            samples = [
                map_forza_row(
                    row,
                    sample_index=index,
                    source_prefix="{0}:lap:{1}".format(session_external_id, lap_number),
                )
                for index, row in enumerate(rows)
            ]
            lap = sessions.upsert_lap(
                stored_session.id,
                LapContract(
                    lap_number=lap_number,
                    source_lap_key="lap:{0}".format(lap_number),
                    started_native_ns=samples[0].native_timestamp_ns,
                    ended_native_ns=samples[-1].native_timestamp_ns,
                    duration_s=(samples[-1].native_timestamp_ns - samples[0].native_timestamp_ns) / 1e9,
                    status="captured",
                    quality={"close_reason": close_reason},
                ),
            )
            lap_ids = {sample.source_sample_key: lap.id for sample in samples}
            telemetry.bulk_upsert_raw(
                source.id,
                stored_session.id,
                samples,
                batch_size=self.batch_size,
                lap_ids_by_sample_key=lap_ids,
            )
            sessions.set_lap_sample_count(lap.id, len(samples))
