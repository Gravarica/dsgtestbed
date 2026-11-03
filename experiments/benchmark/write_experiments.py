from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

HERE = Path(__file__).parent
CONFIGURATIONS_PER_SERVICE = 10
UTILIZATIONS = (0.1, 0.4, 0.6, 0.8, 1.0)
PROBE_CORES = 8
CPU_SLACK = 1.15
QUEUE_THAT_NEVER_FILLS = 1_000_000

QUALITY = {
    "vision": {"from": 160, "to": 640, "step": 32},
    "audio": {"from": 2, "to": 12},
    "lidar": {"from": 6, "to": 40, "step": 2},
}

SERVICES = {
    "cv-analyzer v2": ("vision", {"model_size": [1, 2]}),
    "face-detector v2": ("vision", {"model_size": [1, 2]}),
    "image-transformer v1": ("vision", {}),
    "image-compressor v1": ("vision", {}),
    "edge-detector v1": ("vision", {}),
    "image-denoiser v1": ("vision", {}),
    "motion-detector v1": ("vision", {}),
    "qr-detector v1": ("vision", {}),
    "audio-resampler v1": ("audio", {}),
    "audio-denoiser v1": ("audio", {}),
    "voice-detector v1": ("audio", {}),
    "pitch-tracker v1": ("audio", {}),
    "audio-encoder v1": ("audio", {}),
    "audio-features v1": ("audio", {}),
    "speech-transcriber v1": ("audio", {"model_size": 1}),
    "pc-downsampler v1": ("lidar", {}),
    "ground-remover v1": ("lidar", {}),
    "normal-estimator v1": ("lidar", {}),
    "pc-registrar v1": ("lidar", {}),
    "pc-encoder v1": ("lidar", {}),
    "pc-clusterer v1": ("lidar", {}),
    "pc-visualizer v1": ("lidar", {}),
}


class EveryValueWrittenOut(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


SERVICES_OF_THE_TREES = ("face-detector v2", "cv-analyzer v2", "image-transformer v1")


def benchmark_experiment(service: str, utilization: float, seed: int) -> Dict[str, Any]:
    application, knobs = SERVICES[service]
    return {
        "nodes": {
            "service": {
                "service": service,
                "discipline": "fifo",
                "cores": PROBE_CORES,
                "parallelism": 1,
                "knobs": {"data_quality": QUALITY[application], **knobs},
            }
        },
        "link": "requests",
        "load": {"utilization": utilization},
        "run": {
            "warmup_seconds": 10,
            "measure_seconds": 30,
            "measure_requests": 400,
            "longest_measure_seconds": 180,
            "probe_seconds": 8,
            "cpu_slack": CPU_SLACK,
            "queue_capacity": QUEUE_THAT_NEVER_FILLS,
            "runs": CONFIGURATIONS_PER_SERVICE,
            "seed": seed,
        },
    }


def every_configuration(experiment: Dict[str, Any]) -> Dict[str, Any]:
    del experiment["run"]["runs"]
    return experiment


def write(experiment: Dict[str, Any], file_name: str) -> None:
    text = yaml.dump(experiment, Dumper=EveryValueWrittenOut, sort_keys=False, default_flow_style=None, width=140)
    (HERE / file_name).write_text(text)


def write_benchmark() -> None:
    for number, service in enumerate(SERVICES, start=1):
        name = service.replace(" ", "-")
        for utilization in UTILIZATIONS:
            percent = round(utilization * 100)
            write(benchmark_experiment(service, utilization, seed=number * 100), f"bench-{name}-u{percent:03d}.yaml")
            if service in SERVICES_OF_THE_TREES:
                write(every_configuration(benchmark_experiment(service, utilization, seed=number * 100)),
                      f"grid-{name}-u{percent:03d}.yaml")


if __name__ == "__main__":
    for old in HERE.glob("*.yaml"):
        old.unlink()
    write_benchmark()
