from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple, Union

NODE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
ARROW = "->"

EdgeText = Union[str, Sequence[str]]


class TopologyInvalid(Exception):
    pass


@dataclass(frozen=True)
class Topology:
    node_names: Tuple[str, ...]
    edges: Tuple[Tuple[str, str], ...]

    def next_hops_of(self, node_name: str) -> List[str]:
        return [receiver for sender, receiver in self.edges if sender == node_name]

    def feeders_of(self, node_name: str) -> List[str]:
        return [sender for sender, receiver in self.edges if receiver == node_name]

    def sources(self) -> List[str]:
        return [name for name in self.node_names if not self.feeders_of(name)]

    def from_first_to_last(self) -> List[str]:
        ordered: List[str] = []
        waiting = list(self.node_names)
        while waiting:
            ready = [name for name in waiting if all(feeder in ordered for feeder in self.feeders_of(name))]
            if not ready:
                raise TopologyInvalid(f"the edges form a cycle among {waiting}")
            ordered.extend(ready)
            waiting = [name for name in waiting if name not in ready]
        return ordered


def edge_from(edge: EdgeText) -> Tuple[str, str]:
    parts = [part.strip() for part in edge.split(ARROW)] if isinstance(edge, str) else list(edge)
    if len(parts) != 2 or not all(parts):
        raise TopologyInvalid(f"an edge is written as 'first {ARROW} second', not {edge!r}")
    return parts[0], parts[1]


def topology_of(node_names: Iterable[str], edges: Iterable[EdgeText]) -> Topology:
    names = tuple(node_names)
    if not names:
        raise TopologyInvalid("there are no nodes")
    badly_named = [name for name in names if not NODE_NAME.match(name)]
    if badly_named:
        raise TopologyInvalid(f"node names use small letters, digits and hyphens, and start with a letter: {badly_named}")
    parsed_edges = tuple(edge_from(edge) for edge in edges)
    for sender, receiver in parsed_edges:
        unknown = [name for name in (sender, receiver) if name not in names]
        if unknown:
            raise TopologyInvalid(f"edge {sender} {ARROW} {receiver} names nodes that do not exist: {unknown}")
        if sender == receiver:
            raise TopologyInvalid(f"{sender} feeds itself")
    topology = Topology(names, parsed_edges)
    topology.from_first_to_last()
    return topology
