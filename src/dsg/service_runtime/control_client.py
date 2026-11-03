from __future__ import annotations

from typing import Any, Dict

import requests

from dsg.service_runtime import endpoints


class ServiceRefused(Exception):
    pass


class ControlClient:
    def __init__(self, base_url: str, seconds_to_wait: float = 30):
        self._base_url = base_url
        self._seconds_to_wait = seconds_to_wait
        self._connection = requests.Session()

    def is_reachable(self) -> bool:
        try:
            return requests.get(f"{self._base_url}/{endpoints.STATUS}", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def status(self) -> Dict[str, Any]:
        return requests.get(f"{self._base_url}/{endpoints.STATUS}", timeout=5).json()

    def change_knob(self, knob_name: str, value: Any) -> None:
        if knob_name in endpoints.ELASTIC_WORKBENCH_SCALING_ENDPOINTS:
            self._put(endpoints.ELASTIC_WORKBENCH_SCALING_ENDPOINTS[knob_name], {knob_name: value})
        else:
            self._put(endpoints.CHANGE_ANY_KNOB, {"name": knob_name, "value": value})

    def change_rate(self, rate_per_second: float, client_id: str = endpoints.DEFAULT_CLIENT_ID) -> None:
        self._put(endpoints.CHANGE_RATE, {"client_id": client_id, "rps": rate_per_second})

    def hand_over(self, request_id: str, request_entered_at_ns: int, admission_phase: str, handed_over_by: str) -> None:
        self._put(
            endpoints.HAND_OVER,
            {
                "request_id": request_id,
                "request_entered_at_ns": request_entered_at_ns,
                "admission_phase": admission_phase,
                "handed_over_by": handed_over_by,
            },
        )

    def start_processing(self) -> None:
        self._put(endpoints.START_PROCESSING, {}, timeout=600)

    def start_measurement(self) -> None:
        self._put(endpoints.START_MEASUREMENT, {})

    def stop_processing(self) -> None:
        self._put(endpoints.STOP_PROCESSING, {})

    def _put(self, endpoint: str, parameters: Dict[str, Any], timeout: float = 0) -> None:
        try:
            response = self._connection.put(
                f"{self._base_url}/{endpoint}", params=parameters, timeout=timeout or self._seconds_to_wait
            )
        except requests.RequestException as error:
            raise ServiceRefused(f"{endpoint} {parameters}: {error}")
        if response.status_code != 200:
            raise ServiceRefused(f"{endpoint} {parameters}: {response.status_code} {response.text}")
