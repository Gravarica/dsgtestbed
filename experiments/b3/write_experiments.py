from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

HERE = Path(__file__).parent
CAMERA = "camera"
CAMERA_SERVICE = "frame-source v1"
CAMERA_CORES = 1.0
STAR_MERGE_CORES = 2.5
LEAF_SERVICES = ("cv-analyzer v2", "face-detector v2")
AGGREGATOR_SERVICE = "image-transformer v1"
MODEL_SIZES = [1, 2]
QUALITY = {"from": 160, "to": 640, "step": 32}
SMALL_FRAMES = {"from": 160, "to": 256, "step": 32}
MOST_LEAVES_AT_FULL_QUALITY = 4
CORES_STEP = 0.05
MOST_PROBE_CORES = 2.0
FEWEST_PROBE_CORES = 1.5
CPU_SLACK = 1.15
QUEUE_THAT_NEVER_FILLS = 1_000_000
MEASURED_FRAMES = 1000
WORKERS = 1
SMALL_LANE_CPUS = 14
WHOLE_MACHINE_CPUS = 28
HEIGHTS = range(1, 6)
CORES_OF_ONE_WORKER = WORKERS + 0.5
EVERY_CONFIGURATION_SIX_TIMES = {"runs": 8, "repetitions": 6}

Edges = List[Tuple[str, str]]


class EveryValueWrittenOut(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def leaves(count: int) -> List[str]:
    return [f"leaf-{number}" for number in range(1, count + 1)]


def balanced_tree(levels: int) -> Edges:
    layer = leaves(2 ** (levels - 1))
    edges = [(CAMERA, leaf) for leaf in layer]
    level = 1
    while len(layer) > 1:
        merged = [f"merge-{level}-{number}" for number in range(1, len(layer) // 2 + 1)]
        edges += [(child, merged[position // 2]) for position, child in enumerate(layer)]
        layer, level = merged, level + 1
    return edges


def narrow_tree(depth: int) -> Edges:
    tree_leaves = leaves(depth)
    edges = [(CAMERA, leaf) for leaf in tree_leaves]
    below = tree_leaves[0]
    for level, new_leaf in enumerate(tree_leaves[1:], start=1):
        merge = f"merge-{level}"
        edges += [(below, merge), (new_leaf, merge)]
        below = merge
    return edges


def star_tree(leaf_count: int) -> Edges:
    tree_leaves = leaves(leaf_count)
    return [(CAMERA, leaf) for leaf in tree_leaves] + [(leaf, "merge") for leaf in tree_leaves]


HUNDRED_RUNS = {"runs": 100}
FIFTY_RUNS = {"runs": 50}
EVERY_CONFIGURATION_OF_ONE_LEAF_THREE_TIMES = {"runs": 32, "repetitions": 3}
EVERY_CONFIGURATION_OF_TWO_LEAVES_SOME_TWICE = {"runs": 64, "repetitions": 2, "repeated_share": 0.5625}

TREES = {
    "b3-balanced-1": (balanced_tree(1), EVERY_CONFIGURATION_OF_ONE_LEAF_THREE_TIMES, SMALL_LANE_CPUS),
    "b3-balanced-2": (balanced_tree(2), EVERY_CONFIGURATION_OF_TWO_LEAVES_SOME_TWICE, SMALL_LANE_CPUS),
    "b3-balanced-3": (balanced_tree(3), HUNDRED_RUNS, SMALL_LANE_CPUS),
    "b3-balanced-4": (balanced_tree(4), HUNDRED_RUNS, WHOLE_MACHINE_CPUS),
    "b3-narrow-4": (narrow_tree(4), HUNDRED_RUNS, SMALL_LANE_CPUS),
    "b3-narrow-6": (narrow_tree(6), HUNDRED_RUNS, WHOLE_MACHINE_CPUS),
    "b3-narrow-8": (narrow_tree(8), HUNDRED_RUNS, WHOLE_MACHINE_CPUS),
    "b3-star-4": (star_tree(4), FIFTY_RUNS, SMALL_LANE_CPUS),
    "b3-star-8": (star_tree(8), FIFTY_RUNS, WHOLE_MACHINE_CPUS),
    "b3-star-16": (star_tree(16), FIFTY_RUNS, WHOLE_MACHINE_CPUS),
}


def services_of(edges: Edges) -> List[str]:
    return [name for name in dict.fromkeys(name for edge in edges for name in edge) if name != CAMERA]


def probe_cores(service_count: int, cpus: float) -> float:
    share = (cpus - CAMERA_CORES) / service_count
    cores = min(MOST_PROBE_CORES, math.floor(share / CORES_STEP - 1e-6) * CORES_STEP)
    if cores < FEWEST_PROBE_CORES:
        raise ValueError(f"{service_count} services get only {cores} probe cores each on {cpus} CPUs")
    return round(cores, 2)


def node_of(name: str, cores: float) -> Dict[str, Any]:
    if name.startswith("leaf-"):
        number = int(name.split("-")[1])
        service = LEAF_SERVICES[(number - 1) % len(LEAF_SERVICES)]
        return {"service": service, "discipline": "fifo", "cores": cores, "parallelism": WORKERS, "knobs": {"model_size": MODEL_SIZES}}
    return {"service": AGGREGATOR_SERVICE, "discipline": "fifo", "cores": cores, "parallelism": WORKERS}


def tree_experiment(edges: Edges, runs: Dict[str, Any], cpus: int, seed: int) -> Dict[str, Any]:
    names = services_of(edges)
    merges = [name for name in names if not name.startswith("leaf-")]
    is_star = merges == ["merge"]
    leaf_count = len(names) - len(merges)
    quality = QUALITY if leaf_count <= MOST_LEAVES_AT_FULL_QUALITY else SMALL_FRAMES
    cores = probe_cores(len(names) - is_star, cpus - STAR_MERGE_CORES * is_star)
    nodes = {CAMERA: {"service": CAMERA_SERVICE, "discipline": "fifo", "cores": CAMERA_CORES, "auto_cores": False, "parallelism": WORKERS}}
    nodes.update({name: node_of(name, STAR_MERGE_CORES if is_star and name == "merge" else cores) for name in names})
    return {
        "nodes": nodes,
        "edges": [f"{sender} -> {receiver}" for sender, receiver in edges],
        "link": "requests",
        "fan_in": "join",
        "shared_knobs": {"data_quality": quality},
        "load": {"utilization": 0.5},
        "run": {
            "warmup_seconds": 10,
            "measure_seconds": 30,
            "measure_requests": MEASURED_FRAMES,
            "longest_measure_seconds": 900,
            "probe_seconds": 8,
            "cpu_slack": CPU_SLACK,
            "cap_cores_at_the_probe": True,
            "queue_capacity": QUEUE_THAT_NEVER_FILLS,
            **runs,
            "seed": seed,
        },
    }


def height_experiment(levels: int, seed: int) -> Dict[str, Any]:
    edges = balanced_tree(levels)
    nodes = {CAMERA: {"service": CAMERA_SERVICE, "discipline": "fifo", "cores": CAMERA_CORES, "parallelism": WORKERS}}
    for name in services_of(edges):
        node = node_of(name, CORES_OF_ONE_WORKER)
        node.pop("knobs", None)
        nodes[name] = node
    return {
        "nodes": nodes,
        "edges": [f"{sender} -> {receiver}" for sender, receiver in edges],
        "link": "requests",
        "fan_in": "join",
        "shared_knobs": {"data_quality": SMALL_FRAMES, "model_size": MODEL_SIZES},
        "load": {"utilization": 0.5},
        "run": {
            "warmup_seconds": 10,
            "measure_seconds": 30,
            "measure_requests": MEASURED_FRAMES,
            "longest_measure_seconds": 900,
            "probe_seconds": 8,
            "cores_may_exceed_the_machine": True,
            "queue_capacity": QUEUE_THAT_NEVER_FILLS,
            **EVERY_CONFIGURATION_SIX_TIMES,
            "seed": seed,
        },
    }


def write_heights() -> None:
    for levels in HEIGHTS:
        text = yaml.dump(height_experiment(levels, seed=5000 + levels * 100), Dumper=EveryValueWrittenOut,
                         sort_keys=False, default_flow_style=None, width=140)
        (HERE / f"b3h-height-{levels}.yaml").write_text(text)


def write_trees() -> None:
    for number, (name, (edges, runs, cpus)) in enumerate(TREES.items(), start=1):
        text = yaml.dump(tree_experiment(edges, runs, cpus, seed=3000 + number * 100), Dumper=EveryValueWrittenOut,
                         sort_keys=False, default_flow_style=None, width=140)
        (HERE / f"{name}.yaml").write_text(text)


if __name__ == "__main__":
    for old in HERE.glob("*.yaml"):
        old.unlink()
    write_trees()
    write_heights()
