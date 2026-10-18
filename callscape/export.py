"""Machine-readable exports: JSON nodes/edges and Graphviz DOT."""

from __future__ import annotations

from .graph import ALL_KINDS, CALL_KINDS, Graph
from .model import Symbol


def to_json(graph: Graph) -> dict[str, object]:
    repo = graph.repo
    nodes = [
        {
            "id": s.id,
            "name": s.name,
            "qualname": s.qualname,
            "kind": s.kind,
            "language": s.lang,
            "file": s.path,
            "line": s.line,
            "end_line": s.end_line,
            "signature": s.signature,
            "callers": graph.fan_in(s.index),
            "callees": graph.fan_out(s.index),
        }
        for s in repo.symbols
    ]
    edges = [
        {
            "from": graph.symbol(e.src).id,
            "to": graph.symbol(e.dst).id,
            "kind": e.kind,
            "count": e.count,
            "lines": e.lines,
            "ambiguous": e.ambiguous,
        }
        for e in sorted(graph.edges, key=lambda e: (e.src, e.dst, e.kind))
    ]
    st = graph.stats()
    stats = {
        "files": st["files"],
        "files_by_language": st["files_by_language"],
        "symbols": st["symbols"],
        "symbols_by_kind": st["symbols_by_kind"],
        "edges": st["edges"],
        "edges_by_kind": st["edges_by_kind"],
        "call_sites": st["call_sites"],
        "call_sites_resolved": st["call_sites_resolved"],
        "call_sites_ambiguous": st["call_sites_ambiguous"],
        "cycles": [[graph.symbol(i).id for i in comp] for comp in st["cycles"]],
        "files_with_syntax_errors": st["files_with_syntax_errors"],
    }
    return {"root": repo.root.name, "nodes": nodes, "edges": edges, "stats": stats}


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_dot(graph: Graph, focus: Symbol | None = None, depth: int = 2, types: bool = False) -> str:
    kinds = ALL_KINDS if types else CALL_KINDS
    if focus is not None:
        keep = set(graph.reachable(focus.index, "out", depth, kinds))
        keep |= set(graph.reachable(focus.index, "in", depth, kinds))
    else:
        keep = {s.index for s in graph.repo.symbols}
    edges = [e for e in graph.edges if e.kind in kinds and e.src in keep and e.dst in keep]
    used = {e.src for e in edges} | {e.dst for e in edges}
    if focus is not None:
        used.add(focus.index)

    lines = [
        "digraph callscape {",
        "  rankdir=LR;",
        '  node [shape=box, fontname="Helvetica", fontsize=10];',
    ]
    by_file: dict[str, list[Symbol]] = {}
    for idx in sorted(used):
        s = graph.symbol(idx)
        by_file.setdefault(s.path, []).append(s)
    for n, (path, syms) in enumerate(sorted(by_file.items())):
        lines.append(f"  subgraph cluster_{n} {{")
        lines.append(f"    label={_q(path)}; style=dashed; color=gray60; fontsize=10;")
        for s in syms:
            attrs = [f"label={_q(s.qualname)}"]
            if s.kind in ("class", "struct", "interface", "type"):
                attrs.append("style=rounded")
            if focus is not None and s.index == focus.index:
                attrs.append("style=filled, fillcolor=lightyellow")
            lines.append(f"    n{s.index} [{', '.join(attrs)}];")
        lines.append("  }")
    for e in edges:
        style = {"call": "", "ref": " [style=dashed]", "type": " [style=dotted, color=gray50]"}[
            e.kind
        ]
        lines.append(f"  n{e.src} -> n{e.dst}{style};")
    lines.append("}")
    return "\n".join(lines) + "\n"
