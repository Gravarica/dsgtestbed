from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Dict

from dsg.service_runtime.contract import Knob, UnknownKnob


class ConfigurationLocked(Exception):
    pass


def configuration_id(values: Dict[str, Any]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode()).hexdigest()[:12]


class Configuration:
    def __init__(self, knobs: Dict[str, Knob]):
        self._knobs = knobs
        self._values = {name: knob.default for name, knob in knobs.items()}
        self._locked = False
        self._guard = threading.Lock()

    def change(self, knob_name: str, raw_value: Any) -> Any:
        with self._guard:
            if self._locked:
                raise ConfigurationLocked("knobs cannot change while the service is processing")
            if knob_name not in self._knobs:
                raise UnknownKnob(knob_name)
            self._values[knob_name] = self._knobs[knob_name].validated(raw_value)
            return self._values[knob_name]

    def lock(self) -> None:
        with self._guard:
            self._locked = True

    def values(self) -> Dict[str, Any]:
        with self._guard:
            return dict(self._values)

    def identifier(self) -> str:
        return configuration_id(self.values())
