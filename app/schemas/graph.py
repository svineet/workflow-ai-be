from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class Position(BaseModel):
    x: float
    y: float


class Node(BaseModel):
    id: str
    type: str
    settings: Dict = Field(default_factory=dict)
    position: Optional[Position] = Field(default=None, description="Optional UI canvas coordinates")


class Edge(BaseModel):
    id: str
    from_node: str = Field(alias="from")
    to: str
    kind: str = Field(default="control", description="Edge kind: 'control' (default) or 'tool'")

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
        # Acyclic via topo sort (tool edges are ignored here)
        self._toposort()
        return self

    def _toposort(self) -> List[str]:
        children: Dict[str, List[str]] = {n.id: [] for n in self.nodes}
        indeg: Dict[str, int] = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            if getattr(e, "kind", "control") == "tool":
                continue
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
