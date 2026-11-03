from __future__ import annotations

from pathlib import Path

from dsg.docker_host import DockerHost

import os

from dsg.node import NodeSettings

STACK_COMPOSE_FILE = Path(__file__).parent / "stack" / "compose.yaml"


def prometheus_url(node_settings: NodeSettings) -> str:
    return f"http://127.0.0.1:{node_settings.prometheus_port}"


def environment_for_the_stack(node_settings: NodeSettings) -> dict:
    return {
        **os.environ,
        "DSG_INFRASTRUCTURE_CPUSET": node_settings.infrastructure_cpuset,
        "DSG_PROMETHEUS_PORT": str(node_settings.prometheus_port),
        "DSG_CADVISOR_PORT": str(node_settings.cadvisor_port),
        "DSG_GRAFANA_PORT": str(node_settings.grafana_port),
    }


def start_monitor_stack(docker: DockerHost, node_settings: NodeSettings) -> None:
    docker.start(STACK_COMPOSE_FILE, environment_for_the_stack(node_settings))


def stop_monitor_stack(docker: DockerHost, node_settings: NodeSettings) -> None:
    docker.stop(STACK_COMPOSE_FILE, environment_for_the_stack(node_settings))
