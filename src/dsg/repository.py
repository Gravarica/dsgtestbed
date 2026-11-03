from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIRECTORY = REPOSITORY_ROOT / "services"
RESULTS_DIRECTORY = REPOSITORY_ROOT / "results"
EXPERIMENTS_DIRECTORY = REPOSITORY_ROOT / "experiments"
NODE_FILE = REPOSITORY_ROOT / "node.yaml"
