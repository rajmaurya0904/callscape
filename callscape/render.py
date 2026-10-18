"""Turn a graph into one self-contained, navigable HTML file."""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from importlib import resources

from . import __version__
from .graph import Graph
from .model import REF_CALL, REF_TYPE, REF_VALUE, Ref

DEFAULT_MAX_BODY_LINES = 400
KIND_CODES = {REF_CALL: "c", REF_VALUE: "r", REF_TYPE: "t"}


def _asset(name: str) -> str:
    return resources.files("callscape").joinpath("assets", name).read_text(encoding="utf-8")


def _file_refs(graph: Graph) -> dict[str, tuple[list[int], list[Ref]]]:
    """Resolved refs per file, sorted by line, with a parallel line array for bisecting."""
    table: dict[str, tuple[list[int], list[Ref]]] = {}
    for path, fi in graph.repo.files.items():
        refs = sorted((r for r in fi.refs if r.targets), key=lambda r: (r.line, r.col))
        table[path] = ([r.line for r in refs], refs)
    return table


def _members(graph: Graph) -> dict[int, list[int]]:
    """Map each type-like symbol to the methods declared on it (possibly in other files)."""
    keyed: dict[tuple[str, str], int] = {}
    for sym in graph.repo.symbols:
        if sym.kind in ("class", "struct", "interface", "type"):
            fi = graph.repo.files[sym.path]
            key = fi.directory if sym.lang == "go" else sym.path
            keyed.setdefault((key, sym.qualname), sym.index)
    members: dict[int, list[int]] = {}
    for sym in graph.repo.symbols:
        if sym.parent is None or sym.kind not in ("method", "function"):
            continue
        fi = graph.repo.files[sym.path]
        key = fi.directory if sym.lang == "go" else sym.path
        owner = keyed.get((key, sym.parent))
        if owner is not None:
            members.setdefault(owner, []).append(sym.index)
    return members


def build_payload(graph: Graph, max_body_lines: int = DEFAULT_MAX_BODY_LINES) -> dict[str, object]:
    repo = graph.repo
    file_ids = {path: i for i, path in enumerate(sorted(repo.files))}
    refs_by_file = _file_refs(graph)
    members = _members(graph)
    syms: list[dict[str, object]] = []
    for sym in repo.symbols:
        lines, truncated = repo.source_of(sym, max_body_lines)
        first = sym.body_start
        last = first + len(lines) - 1
        line_keys, file_refs = refs_by_file[sym.path]
        lo = bisect_left(line_keys, first)
        hi = bisect_right(line_keys, last)
        spans = []
        for ref in file_refs[lo:hi]:
            targets = [repo.by_id[t].index for t in ref.targets if t in repo.by_id]
            if targets:
                spans.append(
                    [
                        ref.line - first,
                        ref.col,
                        ref.end_col,
                        targets,
                        KIND_CODES[ref.kind],
                        1 if ref.ambiguous else 0,
                    ]
                )
        syms.append(
            {
                "n": sym.name,
                "q": sym.qualname,
                "k": sym.kind,
                "l": sym.lang,
                "f": file_ids[sym.path],
                "s": sym.line,
                "e": sym.end_line,
                "bs": first,
                "g": sym.signature,
                "d": sym.doc,
                "b": "\n".join(lines),
                "t": 1 if truncated else 0,
                "r": spans,
                "o": _edge_list(graph.out.get(sym.index, ()), outgoing=True),
                "c": _edge_list(graph.inc.get(sym.index, ()), outgoing=False),
                "m": members.get(sym.index, []),
                "x": graph.fan_in(sym.index),
                "y": graph.fan_out(sym.index),
            }
        )
    stats = graph.stats()
    by_file: dict[int, list[int]] = {}
    for sym in repo.symbols:
        by_file.setdefault(file_ids[sym.path], []).append(sym.index)
    files = [
        {
            "p": path,
            "l": repo.files[path].lang,
            "s": by_file.get(i, []),
            "x": int(repo.files[path].has_error),
        }
        for path, i in file_ids.items()
    ]
    return {
        "meta": {
            "name": repo.root.name or str(repo.root),
            "version": __version__,
            "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "skipped": [list(s) for s in repo.skipped],
        },
        "files": files,
        "syms": syms,
        "stats": stats,
    }


def _edge_list(edges, outgoing: bool) -> list[list[object]]:
    rows = []
    for e in edges:
        rows.append(
            [
                e.dst if outgoing else e.src,
                KIND_CODES[e.kind],
                e.count,
                1 if e.ambiguous else 0,
                e.lines[:6],
            ]
        )
    return rows


def render_html(graph: Graph, max_body_lines: int = DEFAULT_MAX_BODY_LINES) -> str:
    payload = build_payload(graph, max_body_lines)
    # Every "<" becomes a JSON unicode escape so source code containing "</script>"
    # or "<!--" cannot terminate or confuse the embedding <script> element.
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    data = data.replace("<", "\\u003c")
    parts = {
        "__TITLE__": _escape(f"callscape: {payload['meta']['name']}"),
        "/*__CSS__*/": _asset("viewer.css"),
        "/*__JS__*/": _asset("viewer.js"),
        "__DATA__": data,
    }
    # One pass, so markers that appear inside the substituted text are left alone.
    pattern = re.compile("|".join(re.escape(k) for k in parts))
    return pattern.sub(lambda m: parts[m.group(0)], _asset("viewer.html"))


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
