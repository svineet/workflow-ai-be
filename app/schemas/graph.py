from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field, model_validator


class Node(BaseModel):
    id: str
    type: str
    params: Dict = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    from_node: str = Field(alias="from")
    to: str

    class Config:
        populate_by_name = True


class Graph(BaseModel):
    nodes: List[Node]
    edges: List[Edge]

    @model_validator(mode="after")
    def _validate_graph(self) -> "Graph":
        node_ids = {n.id for n in self.nodes}
        # Unique node IDs
        if len(node_ids) != len(self.nodes):
            raise ValueError("Duplicate node IDs in graph")
        # All edge endpoints exist
        for e in self.edges:
            if e.from_node not in node_ids or e.to not in node_ids:
                raise ValueError(f"Edge {e.id} references missing node(s)")
        # Acyclic via topo sort
        self._toposort()
        return self

    def _toposort(self) -> List[str]:
        children: Dict[str, List[str]] = {n.id: [] for n in self.nodes}
        indeg: Dict[str, int] = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            children[e.from_node].append(e.to)
            indeg[e.to] += 1
        queue = [nid for nid, d in indeg.items() if d == 0]
        order: List[str] = []
        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for c in children[nid]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if len(order) != len(self.nodes):
            raise ValueError("Graph contains a cycle")
        return order
