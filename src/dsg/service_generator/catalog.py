from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from dsg.repository import SERVICES_DIRECTORY


class ServiceMissing(Exception):
    pass


def image_name(service: str, version: str) -> str:
    return f"dsg/{service}:{version}"


def service_directory(service: str, version: str, services_directory: Path = SERVICES_DIRECTORY) -> Path:
    directory = services_directory / service / version
    if not (directory / "spec.yaml").exists():
        raise ServiceMissing(f"{directory} has no spec.yaml")
    return directory


def list_services(services_directory: Path = SERVICES_DIRECTORY) -> List[Tuple[str, str]]:
    return sorted((spec.parent.parent.name, spec.parent.name) for spec in services_directory.glob("*/*/spec.yaml"))
