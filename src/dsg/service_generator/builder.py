from __future__ import annotations

import subprocess
from pathlib import Path

from dsg.docker_host import DockerHost
from dsg.repository import REPOSITORY_ROOT, SERVICES_DIRECTORY
from dsg.service_generator.catalog import image_name, service_directory

DOCKERFILE = Path(__file__).parent / "service.Dockerfile"

SPEC_SKELETON = """name: {name}
version: {version}
service_type: {name}
input: any
output: bytes
sample_count: 1
knobs:
  work_size: {{type: int, min: 1, max: 1000, default: 100}}
"""

BRIEF_SKELETON = """name: {name}
asked_by: ""
date: ""
task: Skeleton. Returns as many bytes as the knob work_size says.
data: {{source: generate}}
knobs:
  - {{name: work_size, type: int, min: 1, max: 1000, default: 100}}
limits: {{memory: 8g}}
"""

SERVICE_SKELETON = """def init_worker(cfg):
    return None


def process(item, cfg, state):
    return bytes(cfg.work_size)
"""

SERVICE_TEST_SKELETON = """import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem


def test_proof():
    cfg = SimpleNamespace(work_size=10, service_directory=Path(__file__).parent)
    state = service.init_worker(cfg)
    assert service.process(WorkItem(sample_index=0, payload=None), cfg, state) == bytes(10)
"""


PREPARE_SCRIPT = "prepare.sh"


class ServiceAlreadyExists(Exception):
    pass


class PreparationFailed(Exception):
    pass


def new_service(name: str, version: str = "v1", services_directory: Path = SERVICES_DIRECTORY) -> Path:
    directory = services_directory / name / version
    if directory.exists():
        raise ServiceAlreadyExists(str(directory))
    (directory / "data").mkdir(parents=True)
    (directory / "brief.yaml").write_text(BRIEF_SKELETON.format(name=name))
    (directory / "spec.yaml").write_text(SPEC_SKELETON.format(name=name, version=version))
    (directory / "service.py").write_text(SERVICE_SKELETON)
    (directory / "test_service.py").write_text(SERVICE_TEST_SKELETON)
    (directory / "requirements.txt").write_text("")
    return directory


def prepare(service: str, version: str, services_directory: Path = SERVICES_DIRECTORY) -> bool:
    directory = service_directory(service, version, services_directory)
    if not (directory / PREPARE_SCRIPT).exists():
        return False
    finished = subprocess.run(["sh", PREPARE_SCRIPT], cwd=directory, capture_output=True, text=True)
    if finished.returncode != 0:
        raise PreparationFailed(f"{directory / PREPARE_SCRIPT} failed:\n{finished.stderr[-1500:]}")
    return True


def build(service: str, version: str, docker: DockerHost) -> str:
    directory = service_directory(service, version)
    image = image_name(service, version)
    docker.build_image(DOCKERFILE, REPOSITORY_ROOT, image, {"SERVICE_PATH": str(directory.relative_to(REPOSITORY_ROOT))})
    return image


def check(service: str, version: str, docker: DockerHost, quietly: bool = False) -> bool:
    service_directory(service, version)
    command = ["python", "-m", "pytest", "/service", "-q", "-p", "no:cacheprovider"]
    return docker.run_once(image_name(service, version), command, quietly) == 0
