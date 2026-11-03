from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from dsg.node import NodeSettings

CONTROL_PORT_IN_CONTAINER = 8080
METRICS_PORT_IN_CONTAINER = 8000
CLOSED_NETWORK = "closed"
OPEN_NETWORK = "open"
DOOR_IMAGE = "alpine/socat"


@dataclass(frozen=True)
class NodeDeployment:
    name: str
    image: str
    cores: float
    memory_limit: str
    next_hops: List[str] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)


def container_name(project: str, node_name: str) -> str:
    return f"{project}-{node_name}"


def control_url_on_the_host(node_settings: NodeSettings, position: int) -> str:
    return f"http://127.0.0.1:{node_settings.control_port + position}"


def control_url_between_containers(node_name: str) -> str:
    return f"http://{node_name}:{CONTROL_PORT_IN_CONTAINER}"


def records_directory_of(run_directory: Path, node_name: str) -> Path:
    return Path(run_directory) / node_name


def compose_for_pipeline(
    nodes: List[NodeDeployment],
    node_settings: NodeSettings,
    project: str,
    run_directory: Path,
    user: str,
    without_network: bool = False,
) -> Dict[str, Any]:
    compose: Dict[str, Any] = {"name": project, "services": {}}
    for position, node in enumerate(nodes):
        compose["services"][node.name] = service_entry(node, node_settings, project, run_directory, user, position)
    return behind_doors_on_a_closed_network(compose, nodes, node_settings, project) if without_network else compose


def service_entry(
    node: NodeDeployment, node_settings: NodeSettings, project: str, run_directory: Path, user: str, position: int
) -> Dict[str, Any]:
    return {
        "image": node.image,
        "container_name": container_name(project, node.name),
        "user": user,
        "cpus": node.cores,
        "cpuset": node_settings.workload_cpuset,
        "mem_limit": node.memory_limit,
        "environment": {
            "NODE_NAME": node.name,
            "CONTAINER_REF": container_name(project, node.name),
            "DEFAULT_CORES": str(node.cores),
            "NEXT_HOPS": ",".join(control_url_between_containers(next_hop) for next_hop in node.next_hops),
            **node.environment,
        },
        "volumes": [f"{records_directory_of(run_directory, node.name).resolve()}:/records"],
        "ports": [
            f"127.0.0.1:{node_settings.control_port + position}:{CONTROL_PORT_IN_CONTAINER}",
            f"127.0.0.1:{node_settings.metrics_port + position}:{METRICS_PORT_IN_CONTAINER}",
        ],
    }


def behind_doors_on_a_closed_network(
    compose: Dict[str, Any], nodes: List[NodeDeployment], node_settings: NodeSettings, project: str
) -> Dict[str, Any]:
    for position, node in enumerate(nodes):
        service = compose["services"][node.name]
        del service["ports"]
        service["networks"] = [CLOSED_NETWORK]
        compose["services"][f"{node.name}-door"] = {
            "image": DOOR_IMAGE,
            "container_name": f"{container_name(project, node.name)}-door",
            "command": f"tcp-listen:{CONTROL_PORT_IN_CONTAINER},fork,reuseaddr tcp-connect:{node.name}:{CONTROL_PORT_IN_CONTAINER}",
            "cpuset": node_settings.infrastructure_cpuset,
            "networks": [CLOSED_NETWORK, OPEN_NETWORK],
            "ports": [f"127.0.0.1:{node_settings.control_port + position}:{CONTROL_PORT_IN_CONTAINER}"],
        }
    compose["networks"] = {CLOSED_NETWORK: {"internal": True}, OPEN_NETWORK: {}}
    return compose


def write_compose_file(path: Path, compose: Dict[str, Any]) -> None:
    Path(path).write_text(yaml.safe_dump(compose, sort_keys=False))
