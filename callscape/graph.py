"""The call graph: edges between symbols plus the queries the CLI and viewer need."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from .model import REF_CALL, REF_TYPE, REF_VALUE, Symbol
from .repo import Repo

CALL_KINDS = (REF_CALL, REF_VALUE)
ALL_KINDS = (REF_CALL, REF_VALUE, REF_TYPE)


@dataclass
class Edge:
    src: int
    dst: int
    kind: str
    count: int = 0
    lines: list[int] = field(default_factory=list)
    ambiguous: bool = False


class Graph:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.out: dict[int, list[Edge]] = {}
        self.inc: dict[int, list[Edge]] = {}
        self._edges: dict[tuple[int, int, str], Edge] = {}
        self.call_refs = 0
        self.resolved_call_refs = 0
        self.ambiguous_call_refs = 0
        self._build()

    def _build(self) -> None:
        by_id = self.repo.by_id
        for ref in self.repo.refs:
            owner = by_id.get(ref.owner)
            if owner is None:
                continue
            if ref.kind == REF_CALL:
                self.call_refs += 1
                if ref.targets:
                    self.resolved_call_refs += 1
                    if ref.ambiguous:
                        self.ambiguous_call_refs += 1
            for tid in ref.targets:
                target = by_id.get(tid)
                if target is None:
                    continue
                if ref.kind == REF_TYPE and target.index == owner.index:
                    continue
                key = (owner.index, target.index, ref.kind)
                edge = self._edges.get(key)
                if edge is None:
                    edge = Edge(owner.index, target.index, ref.kind)
                    self._edges[key] = edge
                    self.out.setdefault(owner.index, []).append(edge)
                    self.inc.setdefault(target.index, []).append(edge)
                edge.count += 1
                edge.lines.append(ref.line)
                edge.ambiguous = edge.ambiguous or ref.ambiguous

    # -- basic access ---------------------------------------------------------------

    @property
    def edges(self) -> list[Edge]:
        return list(self._edges.values())

    def symbol(self, idx: int) -> Symbol:
        return self.repo.symbols[idx]

    def callees(self, idx: int, kinds: tuple[str, ...] = CALL_KINDS) -> list[Symbol]:
        seen: dict[int, None] = {}
        for e in self.out.get(idx, ()):
            if e.kind in kinds:
                seen.setdefault(e.dst, None)
        return [self.symbol(i) for i in seen]

    def callers(self, idx: int, kinds: tuple[str, ...] = CALL_KINDS) -> list[Symbol]:
        seen: dict[int, None] = {}
        for e in self.inc.get(idx, ()):
            if e.kind in kinds:
                seen.setdefault(e.src, None)
        return [self.symbol(i) for i in seen]

    # -- lookup ---------------------------------------------------------------------

    def lookup(self, query: str) -> list[Symbol]:
        """Find symbols by id, qualified name, bare name, or a ``path::name`` suffix."""
        symbols = [s for s in self.repo.symbols if s.kind != "module"]
        normalised = query.replace("\\", "/")
        tiers = (
            lambda s: s.id == normalised,
            lambda s: s.qualname == normalised,
            lambda s: s.name == normalised,
            lambda s: s.id.endswith("/" + normalised) or s.id.endswith("::" + normalised),
            lambda s: normalised.casefold() in s.qualname.casefold(),
        )
        for test in tiers:
            hits = [s for s in symbols if test(s)]
            if hits:
                return hits
        return []

    # -- traversals -----------------------------------------------------------------

    def reachable(
        self,
        idx: int,
        direction: str = "out",
        max_depth: int | None = None,
        kinds: tuple[str, ...] = CALL_KINDS,
    ) -> dict[int, int]:
        """Breadth-first distances from ``idx`` along calls (``out``) or callers (``in``)."""
        table = self.out if direction == "out" else self.inc
        dist = {idx: 0}
        queue = deque([idx])
        while queue:
            cur = queue.popleft()
            if max_depth is not None and dist[cur] >= max_depth:
                continue
            for e in table.get(cur, ()):
                if e.kind not in kinds:
                    continue
                nxt = e.dst if direction == "out" else e.src
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist

    def shortest_path(
        self, start: int, goal: int, kinds: tuple[str, ...] = CALL_KINDS
    ) -> list[int] | None:
        if start == goal:
            return [start]
        prev: dict[int, int] = {start: start}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for e in self.out.get(cur, ()):
                if e.kind not in kinds or e.dst in prev:
                    continue
                prev[e.dst] = cur
                if e.dst == goal:
                    path = [goal]
                    while path[-1] != start:
                        path.append(prev[path[-1]])
                    return path[::-1]
                queue.append(e.dst)
        return None

    def cycles(self, kinds: tuple[str, ...] = CALL_KINDS) -> list[list[int]]:
        """Strongly connected components with more than one member (mutual recursion)."""
        index_of: dict[int, int] = {}
        low: dict[int, int] = {}
        on_stack: set[int] = set()
        stack: list[int] = []
        result: list[list[int]] = []
        counter = 0
        nodes = sorted({e.src for e in self._edges.values() if e.kind in kinds})

        def neighbours(n: int) -> list[int]:
            return [e.dst for e in self.out.get(n, ()) if e.kind in kinds and e.dst != n]

        for root in nodes:
            if root in index_of:
                continue
            work = [(root, iter(neighbours(root)))]
            index_of[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                node, it = work[-1]
                advanced = False
                for nxt in it:
                    if nxt not in index_of:
                        index_of[nxt] = low[nxt] = counter
                        counter += 1
                        stack.append(nxt)
                        on_stack.add(nxt)
                        work.append((nxt, iter(neighbours(nxt))))
                        advanced = True
                        break
                    if nxt in on_stack:
                        low[node] = min(low[node], index_of[nxt])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index_of[node]:
                    comp = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        comp.append(member)
                        if member == node:
                            break
                    if len(comp) > 1:
                        result.append(sorted(comp))
        result.sort(key=lambda c: (-len(c), c[0]))
        return result

    def recursive(self) -> list[int]:
        return sorted(
            e.src for e in self._edges.values() if e.kind in CALL_KINDS and e.src == e.dst
        )

    # -- summaries ------------------------------------------------------------------

    def fan_in(self, idx: int) -> int:
        return len({e.src for e in self.inc.get(idx, ()) if e.kind in CALL_KINDS})

    def fan_out(self, idx: int) -> int:
        return len({e.dst for e in self.out.get(idx, ()) if e.kind in CALL_KINDS})

    def stats(self) -> dict[str, Any]:
        symbols = self.repo.symbols
        real = [s for s in symbols if s.kind != "module"]
        by_kind = Counter(s.kind for s in real)
        by_lang = Counter(fi.lang for fi in self.repo.files.values())
        edge_kinds = Counter(e.kind for e in self._edges.values())
        callable_syms = [s for s in real if s.kind in ("function", "method")]
        most_called = sorted(callable_syms, key=lambda s: (-self.fan_in(s.index), s.id))
        biggest = sorted(callable_syms, key=lambda s: (-self.fan_out(s.index), s.id))
        entry = [s for s in callable_syms if self.fan_in(s.index) == 0]
        return {
            "files": len(self.repo.files),
            "files_by_language": dict(sorted(by_lang.items())),
            "files_with_syntax_errors": sorted(
                p for p, fi in self.repo.files.items() if fi.has_error
            ),
            "symbols": len(real),
            "symbols_by_kind": dict(sorted(by_kind.items())),
            "edges": len(self._edges),
            "edges_by_kind": dict(sorted(edge_kinds.items())),
            "call_sites": self.call_refs,
            "call_sites_resolved": self.resolved_call_refs,
            "call_sites_ambiguous": self.ambiguous_call_refs,
            "most_called": [
                (s.index, self.fan_in(s.index))
                for s in most_called[:10]
                if self.fan_in(s.index) > 0
            ],
            "most_calling": [
                (s.index, self.fan_out(s.index)) for s in biggest[:10] if self.fan_out(s.index) > 0
            ],
            "entry_points": [s.index for s in entry],
            "cycles": self.cycles(),
            "recursive": self.recursive(),
        }
