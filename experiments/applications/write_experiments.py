from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

HERE = Path(__file__).parent
RUNS_PER_FILE = 150
UNTHROTTLED_RUNS_PER_FILE = 50
QUEUE_THAT_NEVER_FILLS = 1_000_000

SHARED_QUALITY = {
    "vision": {"from": 160, "to": 640, "step": 32},
    "audio": {"from": 2, "to": 12},
    "lidar": {"from": 6, "to": 40, "step": 2},
}

SERVICES = {
    "detector": ("cv-analyzer v2", {"model_size": [1, 2]}),
    "faces": ("face-detector v2", {"model_size": [1, 2]}),
    "transformer": ("image-transformer v1", {}),
    "compressor": ("image-compressor v1", {}),
    "edges": ("edge-detector v1", {}),
    "denoiser": ("image-denoiser v1", {}),
    "motion": ("motion-detector v1", {}),
    "codes": ("qr-detector v1", {}),
    "resampler": ("audio-resampler v1", {}),
    "cleaner": ("audio-denoiser v1", {}),
    "voice": ("voice-detector v1", {}),
    "pitch": ("pitch-tracker v1", {}),
    "encoder": ("audio-encoder v1", {}),
    "features": ("audio-features v1", {}),
    "transcriber": ("speech-transcriber v1", {"model_size": 1}),
    "downsampler": ("pc-downsampler v1", {}),
    "ground": ("ground-remover v1", {}),
    "normals": ("normal-estimator v1", {}),
    "registrar": ("pc-registrar v1", {}),
    "packer": ("pc-encoder v1", {}),
    "clusterer": ("pc-clusterer v1", {}),
    "viewer": ("pc-visualizer v1", {}),
}

CHAINS = {
    "vision": [
        ["detector", "transformer", "compressor"],
        ["faces", "transformer", "edges"],
        ["denoiser", "detector", "faces", "compressor"],
        ["transformer", "denoiser", "motion", "codes", "edges"],
        ["motion", "codes", "detector", "faces", "edges", "compressor"],
    ],
    "audio": [
        ["resampler", "cleaner", "features"],
        ["cleaner", "voice", "encoder"],
        ["resampler", "voice", "pitch", "encoder"],
        ["cleaner", "voice", "transcriber"],
        ["resampler", "pitch", "features", "transcriber", "encoder"],
    ],
    "lidar": [
        ["downsampler", "ground", "clusterer"],
        ["ground", "normals", "packer"],
        ["downsampler", "registrar", "viewer"],
        ["ground", "clusterer", "viewer", "packer"],
        ["downsampler", "normals", "registrar", "clusterer", "packer"],
    ],
}

WORKERS = {
    "single": {"cores": [1, 1.5, 2], "parallelism": 1},
    "workers": {"cores": {"from": 1, "to": 4}, "parallelism": [1, 2, 3, 4]},
    "unthrottled": {"cores_beyond_the_workers": 0.5, "parallelism": [1, 2, 3, 4]},
}
BASE_CASE = ("single", "workers")


class EveryValueWrittenOut(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def chain_experiment(application: str, chain: List[str], workers: str, load: Dict[str, Any], runs: int, seed: int) -> Dict[str, Any]:
    nodes = {}
    for name in chain:
        service, knobs = SERVICES[name]
        nodes[name] = {"service": service, "discipline": "fifo", **WORKERS[workers]}
        if knobs:
            nodes[name]["knobs"] = dict(knobs)
    return {
        "nodes": nodes,
        "edges": [f"{sender} -> {receiver}" for sender, receiver in zip(chain, chain[1:])],
        "link": "requests",
        "shared_knobs": {"data_quality": SHARED_QUALITY[application]},
        "load": load,
        "run": {
            "warmup_seconds": 10,
            "measure_seconds": 30,
            "measure_requests": 400,
            "longest_measure_seconds": 180,
            "probe_seconds": 8,
            "queue_capacity": QUEUE_THAT_NEVER_FILLS,
            "runs": runs,
            "seed": seed,
        },
    }


def write(file_name: str, experiment: Dict[str, Any]) -> None:
    text = yaml.dump(experiment, Dumper=EveryValueWrittenOut, sort_keys=False, default_flow_style=None, width=140)
    (HERE / file_name).write_text(text)


def write_base_case() -> None:
    for application_number, (application, chains) in enumerate(CHAINS.items(), start=1):
        for chain_number, chain in enumerate(chains, start=1):
            for workers_number, workers in enumerate(BASE_CASE, start=1):
                write(
                    f"b1-{application}-{chain_number}-{workers}.yaml",
                    chain_experiment(
                        application,
                        chain,
                        workers,
                        load={"utilization": 0.5},
                        runs=RUNS_PER_FILE,
                        seed=application_number * 1000 + chain_number * 10 + workers_number,
                    ),
                )


UNTHROTTLED_BATCHES = {"b1u": 7, "b1u2": 8}


def write_unthrottled() -> None:
    for prefix, seed_digit in UNTHROTTLED_BATCHES.items():
        write_unthrottled_batch(prefix, seed_digit)


def write_unthrottled_batch(prefix: str, seed_digit: int) -> None:
    for application_number, (application, chains) in enumerate(CHAINS.items(), start=1):
        for chain_number, chain in enumerate(chains, start=1):
            write(
                f"{prefix}-{application}-{chain_number}.yaml",
                chain_experiment(
                    application,
                    chain,
                    "unthrottled",
                    load={"utilization": 0.5},
                    runs=UNTHROTTLED_RUNS_PER_FILE,
                    seed=application_number * 1000 + chain_number * 10 + seed_digit,
                ),
            )


B4_CHAIN = ("vision", 1)
B4_LOADS = (0.1, 0.25, 0.4, 0.7, 0.9, 1.0)
B4_VARIABILITIES = (0, 0.1, 0.3, 0.6, 1.5, 2, 3, 4)


def b4_experiment(prefix: str, seed_digit: int, load: Dict[str, Any]) -> Dict[str, Any]:
    application, chain_number = B4_CHAIN
    application_number = list(CHAINS).index(application) + 1
    return chain_experiment(
        application,
        CHAINS[application][chain_number - 1],
        "unthrottled",
        load=load,
        runs=UNTHROTTLED_RUNS_PER_FILE,
        seed=application_number * 1000 + chain_number * 10 + seed_digit,
    )


def write_b4() -> None:
    for prefix, seed_digit in UNTHROTTLED_BATCHES.items():
        batch = prefix.replace("b1u", "")
        for utilization in B4_LOADS:
            write(f"b4a{batch}-utilization-{utilization:g}.yaml", b4_experiment(prefix, seed_digit, {"utilization": utilization}))
        for variability in B4_VARIABILITIES:
            load = {"utilization": 0.5, "arrival_process": "renewal", "arrival_variability": variability}
            write(f"b4b{batch}-variability-{variability:g}.yaml", b4_experiment(prefix, seed_digit, load))


if __name__ == "__main__":
    for old in HERE.glob("*.yaml"):
        old.unlink()
    write_base_case()
    write_unthrottled()
    write_b4()
