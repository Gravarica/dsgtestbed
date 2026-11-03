from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

import yaml


class SpecInvalid(Exception):
    pass


class ServiceInvalid(Exception):
    pass


class UnknownKnob(Exception):
    pass


class KnobValueRejected(Exception):
    pass


@dataclass(frozen=True)
class Knob:
    name: str
    kind: str
    default: Any
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[str, ...] = ()

    def validated(self, raw_value: Any) -> Any:
        if self.kind == "choice":
            return self._validated_choice(raw_value)
        return self._validated_number(raw_value)

    def _validated_choice(self, raw_value: Any) -> str:
        value = str(raw_value)
        if value not in self.choices:
            raise KnobValueRejected(f"{self.name}={value} is not one of {list(self.choices)}")
        return value

    def _validated_number(self, raw_value: Any) -> Any:
        try:
            number = float(raw_value)
        except (TypeError, ValueError):
            raise KnobValueRejected(f"{self.name}={raw_value!r} is not a number")
        if self.kind == "int" and number != int(number):
            raise KnobValueRejected(f"{self.name}={raw_value} is not a whole number")
        if number < self.minimum or number > self.maximum:
            raise KnobValueRejected(f"{self.name}={raw_value} is outside [{self.minimum}, {self.maximum}]")
        return int(number) if self.kind == "int" else number


HARNESS_KNOBS: Dict[str, Knob] = {
    "parallelism": Knob("parallelism", "int", default=1, minimum=1, maximum=64),
    "discipline": Knob("discipline", "choice", default="window", choices=("window", "fifo")),
    "window_ms": Knob("window_ms", "int", default=1000, minimum=10, maximum=60000),
    "batch_size": Knob("batch_size", "int", default=1000, minimum=1, maximum=1000000),
}

REQUIRED_SPEC_FIELDS = ("name", "version", "service_type", "input", "output")


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    version: str
    service_type: str
    input_type: str
    output_type: str
    sample_count: int
    application_knobs: Dict[str, Knob]

    def all_knobs(self) -> Dict[str, Knob]:
        return {**HARNESS_KNOBS, **self.application_knobs}


def knob_from_declaration(name: str, declaration: Dict[str, Any]) -> Knob:
    if declaration["type"] == "choice":
        return Knob(name, "choice", default=declaration["default"], choices=tuple(declaration["values"]))
    return Knob(name, declaration["type"], declaration["default"], declaration["min"], declaration["max"])


def service_spec_from_mapping(document: dict) -> ServiceSpec:
    missing = [field for field in REQUIRED_SPEC_FIELDS if field not in document]
    if missing:
        raise SpecInvalid(f"spec is missing {missing}")
    declared_knobs = document.get("knobs") or {}
    redeclared = sorted(set(declared_knobs) & set(HARNESS_KNOBS))
    if redeclared:
        raise SpecInvalid(f"spec redeclares harness knobs {redeclared}")
    if document["output"] == "any":
        raise SpecInvalid("output type 'any' is not allowed")
    return ServiceSpec(
        name=document["name"],
        version=str(document["version"]),
        service_type=document["service_type"],
        input_type=document["input"],
        output_type=document["output"],
        sample_count=int(document.get("sample_count", 1)),
        application_knobs={name: knob_from_declaration(name, declared) for name, declared in declared_knobs.items()},
    )


def load_service_spec(service_directory: Path) -> ServiceSpec:
    with (Path(service_directory) / "spec.yaml").open() as spec_file:
        return service_spec_from_mapping(yaml.safe_load(spec_file))


@dataclass(frozen=True)
class WorkItem:
    sample_index: int
    payload: Optional[bytes]


class Outputs(list):
    pass


def outputs_from(returned: Any) -> List[Any]:
    if returned is None:
        return []
    if isinstance(returned, Outputs):
        return list(returned)
    return [returned]


def size_in_bytes(output: Any) -> int:
    if isinstance(output, (bytes, bytearray)):
        return len(output)
    return int(getattr(output, "nbytes", 0))


def load_service_module(service_directory: Path) -> ModuleType:
    service_file = Path(service_directory) / "service.py"
    if not service_file.exists():
        raise ServiceInvalid(f"{service_file} does not exist")
    if str(service_directory) not in sys.path:
        sys.path.insert(0, str(service_directory))
    module_spec = importlib.util.spec_from_file_location("loaded_service", service_file)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    if not callable(getattr(module, "process", None)):
        raise ServiceInvalid(f"{service_file} does not define process(item, cfg, state)")
    return module
