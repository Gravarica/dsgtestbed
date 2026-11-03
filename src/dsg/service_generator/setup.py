from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from dsg.docker_host import DockerHost
from dsg.service_generator import builder
from dsg.service_generator.catalog import image_name, list_services

READY = "ready"
FAILED = "failed"


@dataclass(frozen=True)
class ServiceSetup:
    service: str
    version: str
    fetched: str
    built: str
    checked: str
    outcome: str
    problem: str = ""


def set_up_every_service(docker: DockerHost, tell: Callable[[str], None], rebuild: bool = False) -> List[ServiceSetup]:
    outcomes = []
    for service, version in list_services():
        outcomes.append(set_up_service(service, version, docker, tell, rebuild))
    return outcomes


def set_up_service(service: str, version: str, docker: DockerHost, tell: Callable[[str], None], rebuild: bool) -> ServiceSetup:
    label = f"{service} {version}"
    try:
        tell(f"{label}: fetching what it needs...")
        fetched = "fetched" if builder.prepare(service, version) else "nothing to fetch"
        if docker.image_exists(image_name(service, version)) and not rebuild:
            built = "image already built"
        else:
            tell(f"{label}: building the image...")
            builder.build(service, version, docker)
            built = "built"
        tell(f"{label}: running its own tests inside the image...")
        checked = "tests pass" if builder.check(service, version, docker, quietly=True) else "tests FAIL"
        outcome = READY if checked == "tests pass" else FAILED
        return ServiceSetup(service, version, fetched, built, checked, outcome)
    except Exception as problem:
        return ServiceSetup(service, version, "", "", "", FAILED, str(problem)[-300:])


def setup_report(outcomes: List[ServiceSetup]) -> str:
    lines = [f"{o.service:22} {o.version:5} {o.fetched:18} {o.built:22} {o.checked:12} {o.outcome}" for o in outcomes]
    for outcome in outcomes:
        if outcome.problem:
            lines.append(f"  {outcome.service}: {outcome.problem}")
    ready = sum(1 for outcome in outcomes if outcome.outcome == READY)
    lines.append(f"{ready} of {len(outcomes)} services ready")
    return "\n".join(lines)
