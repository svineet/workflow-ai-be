from __future__ import annotations

from typing import Dict, List, Tuple

from ..schemas.graph import Graph


def toposort(graph: Graph) -> List[str]:
    return graph._toposort()


def build_parent_child_maps(graph: Graph) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    parents: Dict[str, List[str]] = {n.id: [] for n in graph.nodes}
    children: Dict[str, List[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        parents[e.to].append(e.from_node)
        children[e.from_node].append(e.to)
    return parents, children
