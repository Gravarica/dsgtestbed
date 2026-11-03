from __future__ import annotations

from typing import Dict, List, Optional

import requests


class PrometheusConnection:
    def __init__(self, url: str):
        self._url = url.rstrip("/")

    def is_up(self) -> bool:
        try:
            return requests.get(f"{self._url}/-/ready", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def query(self, promql: str) -> List[Dict]:
        response = requests.get(f"{self._url}/api/v1/query", params={"query": promql}, timeout=5)
        response.raise_for_status()
        return response.json()["data"]["result"]

    def latest_value(self, metric_name: str, container_id: str) -> Optional[float]:
        result = self.query(f'{metric_name}{{container_id="{container_id}"}}')
        return float(result[0]["value"][1]) if result else None

    def latest_values(self, metric_names: List[str], container_id: str) -> Dict[str, float]:
        selector = "|".join(metric_names)
        result = self.query(f'{{__name__=~"{selector}",container_id="{container_id}"}}')
        return {series["metric"]["__name__"]: float(series["value"][1]) for series in result}

    def scrape_targets(self) -> Dict[str, str]:
        response = requests.get(f"{self._url}/api/v1/targets", timeout=5)
        response.raise_for_status()
        return {target["scrapeUrl"]: target["health"] for target in response.json()["data"]["activeTargets"]}
