from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional


class DockerCommandFailed(Exception):
    pass


class DockerHost:
    def build_image(self, dockerfile: Path, context: Path, image: str, build_arguments: Dict[str, str]) -> None:
        arguments = [part for name, value in build_arguments.items() for part in ("--build-arg", f"{name}={value}")]
        self._show(["docker", "build", "-f", str(dockerfile), *arguments, "-t", image, str(context)])

    def run_once(self, image: str, command: List[str], quietly: bool = False) -> int:
        return subprocess.run(["docker", "run", "--rm", image, *command], capture_output=quietly).returncode

    def start(self, compose_file: Path, environment: Optional[Dict[str, str]] = None) -> None:
        self._capture(["docker", "compose", "-f", str(compose_file), "up", "-d"], environment=environment)

    def stop(self, compose_file: Path, environment: Optional[Dict[str, str]] = None) -> None:
        self._capture(["docker", "compose", "-f", str(compose_file), "down", "--timeout", "10"], environment=environment)

    def change_cores(self, container: str, cores: float) -> None:
        self._capture(["docker", "update", "--cpus", f"{cores:g}", container])

    def image_exists(self, image: str) -> bool:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0

    def image_id(self, image: str) -> str:
        return self._capture(["docker", "image", "inspect", "-f", "{{.Id}}", image]).strip()

    def is_running(self, container: str) -> bool:
        return self._inspect(container, "{{.State.Running}}") == "true"

    def was_killed_for_memory(self, container: str) -> bool:
        return self._inspect(container, "{{.State.OOMKilled}}") == "true"

    def logs(self, container: str) -> str:
        return self._capture(["docker", "logs", "--tail", "200", container], must_succeed=False)

    def read_file(self, container: str, path: str) -> str:
        return self._capture(["docker", "exec", container, "cat", path], must_succeed=False)

    def _inspect(self, container: str, template: str) -> str:
        return self._capture(["docker", "inspect", "-f", template, container], must_succeed=False).strip()

    def _show(self, command: List[str]) -> None:
        if subprocess.run(command).returncode != 0:
            raise DockerCommandFailed(" ".join(command))

    def _capture(self, command: List[str], must_succeed: bool = True, environment: Optional[Dict[str, str]] = None) -> str:
        finished = subprocess.run(command, capture_output=True, text=True, env=environment)
        if must_succeed and finished.returncode != 0:
            raise DockerCommandFailed(f"{' '.join(command)}\n{finished.stderr}")
        return finished.stdout if must_succeed else finished.stdout + finished.stderr
