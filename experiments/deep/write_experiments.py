from __future__ import annotations

import math
import random
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

HERE = Path(__file__).parent
WEEKEND = HERE.parent / "weekend"
BURSTS = {"burst_factor": [1, 2, 4], "burst_seconds": [1, 2]}
SECONDS_OF_WARMUP_PER_HOP = 0.7


class EveryValueWrittenOut(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True

CHEAP_AT_HALF_A_CORE = {
    "hash-signer": ("signer", {"data_quality": 4, "algorithm": "sha256", "rounds": 3000}),
    "sensor-aggregator": ("agg", {"window_length": 512, "channels": 8, "feature_set": "basic"}),
    "audio-features": ("audio", {"data_quality": 4, "mel_bands": 40, "frame_ms": 25}),
    "log-parser": ("logs", {"data_quality": 200, "pattern_count": 20}),
    "text-indexer": ("idx", {"data_quality": 50, "compression_level": 6, "ngram_size": 2}),
    "face-detector": ("face", {"model_size": 1}),
    "pc-visualizer": ("lidar", {"data_quality": 30}),
    "image-compressor": ("camera", {"data_quality": 552, "encoding_quality": 75, "format": "jpeg"}),
}

LIGHT_RANGES = {
    "hash-signer": ("signer", {"data_quality": [1, 4, 16], "algorithm": ["sha256", "blake2b"], "rounds": [1000, 3000, 10000]}),
    "sensor-aggregator": ("agg", {"window_length": [256, 512, 1024], "channels": [4, 8, 16], "feature_set": ["basic", "spectral"]}),
    "audio-features": ("audio", {"data_quality": [2, 4, 6], "mel_bands": [20, 40, 64], "frame_ms": [20, 25, 40]}),
    "log-parser": ("logs", {"data_quality": [100, 200, 500], "pattern_count": [5, 20, 50]}),
    "text-indexer": ("idx", {"data_quality": [10, 50, 100], "compression_level": [1, 6, 9], "ngram_size": [1, 2]}),
    "face-detector": ("face", {"model_size": [1, 2]}),
    "pc-visualizer": ("lidar", {"data_quality": [6, 30, 60]}),
    "image-compressor": ("camera", {"data_quality": [300, 552, 800], "encoding_quality": [50, 75, 90], "format": "jpeg"}),
    "qr-detector": ("qr", {"data_quality": [300, 552]}),
    "cv-analyzer": ("cv", {"model_size": 1, "data_quality": [128, 160]}),
    "table-joiner": ("tables", {"data_quality": [1000, 3000, 10000], "group_count": [10, 100, 1000]}),
    "anomaly-detector": ("anomaly", {"model_size": 1, "window_length": [512, 1024, 2048], "threshold": 3.5}),
    "pc-clusterer": ("cluster", {"data_quality": [10, 20, 30], "voxel_size": [0.5, 0.75, 1.0], "cluster_distance": 0.7}),
}

SENSORS = ["anomaly-detector", "audio-features", "image-compressor", "pc-clusterer", "log-parser", "hash-signer"]


def write(file_name: str, experiment: Dict[str, Any]) -> None:
    (HERE / file_name).write_text(yaml.dump(experiment, Dumper=EveryValueWrittenOut, sort_keys=False, default_flow_style=None, width=140))


def chained(names: List[str]) -> List[str]:
    return [f"{sender} -> {receiver}" for sender, receiver in zip(names, names[1:])]


def warmup_for(hops: int) -> int:
    return 5 + math.ceil(SECONDS_OF_WARMUP_PER_HOP * hops)


def depth_curve_nodes(depth: int) -> Dict[str, Any]:
    cycle = list(CHEAP_AT_HALF_A_CORE)
    nodes = {}
    for position in range(depth):
        service = cycle[position % len(cycle)]
        short_name, knobs = CHEAP_AT_HALF_A_CORE[service]
        nodes[f"{short_name}-{position + 1:02d}"] = {"service": f"{service} v1", "cores": 0.5, "knobs": dict(knobs)}
    return nodes


def write_depth_curve(prefix: str) -> None:
    for depth in (1, 2, 5, 10, 20, 35, 50):
        nodes = depth_curve_nodes(depth)
        for link, repetitions in (("requests", 3), ("rates", 1)):
            if link == "rates" and depth not in (5, 10, 20, 35):
                continue
            write(
                f"{prefix}-depth-{depth:02d}-{link}.yaml",
                {
                    "nodes": nodes,
                    "edges": chained(list(nodes)),
                    "link": link,
                    "load": {"rps": [5, 10, 20], "burst_factor": [1, 2, 4], "burst_seconds": 1},
                    "run": {"warmup_seconds": warmup_for(depth), "measure_seconds": 30, "repetitions": repetitions, "seed": 1000 + depth},
                },
            )


def write_random_chains(prefix: str, depth: int, count: int, cores: Dict[str, Any], seed: int) -> None:
    randomness = random.Random(seed)
    pool = list(LIGHT_RANGES)
    for index in range(count):
        nodes = {}
        for position, service in enumerate(randomness.choices(pool, k=depth)):
            short_name, knobs = LIGHT_RANGES[service]
            nodes[f"{short_name}-{position + 1:02d}"] = {"service": f"{service} v1", "cores": cores, "knobs": dict(knobs)}
        write(
            f"{prefix}-chain-{depth:02d}-{chr(ord('a') + index)}.yaml",
            {
                "nodes": nodes,
                "edges": chained(list(nodes)),
                "link": "requests",
                "load": {"rps": {"from": 5, "to": 30, "step": 5}, **BURSTS},
                "run": {"warmup_seconds": warmup_for(depth), "measure_seconds": 30, "runs": 40, "seed": seed + index},
            },
        )


def tree_levels(branching: int, height: int) -> List[List[str]]:
    levels = [["root"]]
    for level in range(1, height + 1):
        levels.append([f"{parent}-{child}" for parent in levels[-1] for child in range(1, branching + 1)])
    return levels


def write_tree(file_name: str, branching: int, height: int, seed: int) -> None:
    levels = tree_levels(branching, height)
    leaves = levels[-1]
    node_count = sum(len(level) for level in levels)
    cores_per_node = {"from": 0.5, "to": 1.5, "step": 0.25} if node_count <= 15 else [0.5, 0.75]
    highest_leaf_rate = min(20, 300 // len(leaves))
    nodes: Dict[str, Any] = {}
    for position, leaf in enumerate(leaves):
        service = SENSORS[position % len(SENSORS)]
        short_name, knobs = LIGHT_RANGES[service]
        nodes[f"{short_name}-{leaf}"] = {
            "service": f"{service} v1",
            "rps": {"from": 2, "to": highest_leaf_rate, "step": 2},
            "cores": cores_per_node,
            "knobs": dict(knobs),
        }
    _, aggregator_knobs = LIGHT_RANGES["sensor-aggregator"]
    for level in levels[1:-1]:
        for inner in level:
            nodes[f"agg-{inner}"] = {"service": "sensor-aggregator v1", "cores": cores_per_node, "knobs": dict(aggregator_knobs)}
    nodes["agg-root"] = {"service": "sensor-aggregator v1", "cores": {"from": 1, "to": 2, "step": 0.5}, "parallelism": 2, "knobs": dict(aggregator_knobs)}
    name_of = {name.split("-", 1)[1] if not name.startswith("agg-") else name[4:]: name for name in nodes}
    edges = [f"{name_of[child]} -> {name_of[child.rsplit('-', 1)[0]]}" for level in levels[1:] for child in level]
    write(
        file_name,
        {
            "nodes": nodes,
            "edges": edges,
            "link": "requests",
            "load": dict(BURSTS),
            "run": {"warmup_seconds": warmup_for(height), "measure_seconds": 30, "runs": 100, "seed": seed},
        },
    )


def rewritten_weekend_file(weekend_name: str, runs: int, seed_offset: int) -> str:
    text = (WEEKEND / weekend_name).read_text()
    text = re.sub(r"(camera:\n    service: image-compressor v1\n    rps: )\{from: 5, to: 60, step: 5\}", r"\1{from: 5, to: 30, step: 5}", text)
    text = re.sub(r"runs: \d+", f"runs: {runs}", text)
    return re.sub(r"seed: (\d+)", lambda found: f"seed: {int(found.group(1)) + seed_offset}", text)


def write_weekend_repeats(prefix: str) -> None:
    for weekend_name in ("01-iot-tree-small.yaml", "03-iot-tree-large.yaml"):
        (HERE / f"{prefix}-{weekend_name}").write_text(rewritten_weekend_file(weekend_name, runs=150, seed_offset=100))
    for weekend_path in sorted(WEEKEND.glob("04*.yaml")):
        text = rewritten_weekend_file(weekend_path.name, runs=25, seed_offset=100)
        if "image-compressor" in text:
            text = text.replace("rps: {from: 5, to: 60, step: 5}", "rps: {from: 5, to: 30, step: 5}")
        (HERE / f"{prefix}-{weekend_path.name}").write_text(text)


def write_noise_repeats(prefix: str) -> None:
    for weekend_path in sorted(WEEKEND.glob("02*.yaml")) + sorted(WEEKEND.glob("07[acd]*.yaml")):
        experiment = yaml.safe_load(weekend_path.read_text())
        rps = experiment["load"]["rps"]
        experiment["load"] = {"rps": {**rps, "to": max(rps["from"], rps["to"] / 2)}, "burst_factor": 1}
        node = next(iter(experiment["nodes"].values()))
        node["cores"], node["parallelism"] = {"from": 2, "to": 4}, [1, 2]
        experiment["run"] = {"warmup_seconds": 5, "measure_seconds": 30, "runs": 3, "repetitions": 5, "seed": experiment["run"]["seed"] + 200}
        write(f"{prefix}-{weekend_path.name[4:]}", experiment)


if __name__ == "__main__":
    for old in HERE.glob("*.yaml"):
        old.unlink()
    write_depth_curve("01")
    for height_and_branching, (branching, height) in enumerate(((2, 2), (3, 2), (2, 3), (2, 4), (3, 3))):
        write_tree(f"02-tree-{branching}x{height}.yaml", branching, height, seed=2000 + height_and_branching)
    write_random_chains("03", depth=10, count=6, cores={"from": 0.5, "to": 1.5, "step": 0.25}, seed=3100)
    write_random_chains("03", depth=20, count=4, cores=[0.5, 0.75, 1.0], seed=3200)
    write_weekend_repeats("04")
    write_noise_repeats("05")
