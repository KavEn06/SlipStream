from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class HuggingFaceSourceManifest:
    key: str
    repo_id: str
    revision: str
    filename: str
    license: str
    simulator: str
    sampling_hz: float
    expected_rows: int
    track_id: str
    track_name: str
    track_layout: str
    car_id: str
    car_name: str
    source_laps: int

    @property
    def source_url(self) -> str:
        return "https://huggingface.co/datasets/{0}/resolve/{1}/{2}".format(
            self.repo_id, self.revision, self.filename
        )


HF_SOURCE_MANIFESTS: Dict[str, HuggingFaceSourceManifest] = {
    "spa": HuggingFaceSourceManifest(
        key="hf:nasim435:spa-francorchamps",
        repo_id="Nasim435/spa-francorchamps-lap-data",
        revision="5d20fbfbbf9958549fc6edd8793dcda1bb5b6f50",
        filename="telemetry.parquet",
        license="MIT",
        simulator="Assetto Corsa",
        sampling_hz=100.0,
        expected_rows=51554,
        track_id="spa",
        track_name="Spa-Francorchamps",
        track_layout="spa",
        car_id="chevrolet_corvette_c7r",
        car_name="Chevrolet Corvette C7.R",
        source_laps=5,
    ),
    "nurburgring_gp": HuggingFaceSourceManifest(
        key="hf:nasim435:nurburgring-gp",
        repo_id="Nasim435/Nurburgring-GP-Lap-data",
        revision="89edbc576f98f85da49935be0c98f9bb056c3e3c",
        filename="telemetry.parquet",
        license="MIT",
        simulator="Assetto Corsa",
        sampling_hz=100.0,
        expected_rows=91490,
        track_id="ks_nurburgring",
        track_name="Nürburgring GP",
        track_layout="GP",
        car_id="ks_lamborghini_sesto_elemento",
        car_name="Lamborghini Sesto Elemento",
        source_laps=10,
    ),
    "imola": HuggingFaceSourceManifest(
        key="hf:nasim435:imola",
        repo_id="Nasim435/Imola-lap-data",
        revision="baebec752f715a2af9c9a221a512b6d81ceccef8",
        filename="telemetry.parquet",
        license="MIT",
        simulator="Assetto Corsa",
        sampling_hz=100.0,
        expected_rows=116987,
        track_id="imola",
        track_name="Imola",
        track_layout="Grand Prix",
        car_id="ferrari_458_gt2",
        car_name="Ferrari 458 GT2",
        source_laps=15,
    ),
}

EXPECTED_HF_ROWS = sum(manifest.expected_rows for manifest in HF_SOURCE_MANIFESTS.values())
