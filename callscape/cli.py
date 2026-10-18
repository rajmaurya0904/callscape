"""Command line interface: ``callscape build|stats|callers|callees|path|dot|json``."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .export import to_dot, to_json
from .graph import ALL_KINDS, CALL_KINDS, Graph
from .model import Symbol
from .render import DEFAULT_MAX_BODY_LINES, render_html
from .repo import load_repo
from .scan import ScanError

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAIL) -> None:
        super().__init__(message)
        self.code = code


def _add_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", nargs="?", default=".", help="repository directory (default: .)")
    p.add_argument(
        "--lang",
        metavar="LIST",
        help="comma-separated languages to analyse: python, javascript, go (default: all)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching this glob (repeatable), e.g. --exclude 'tests/*'",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="callscape",
        description="Build a navigable call graph of a Python, JavaScript and Go repository.",
    )
    parser.add_argument("--version", action="version", version=f"callscape {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    b = sub.add_parser("build", help="write a self-contained HTML call graph")
    _add_source_args(b)
    b.add_argument(
        "-o", "--output", default="callscape.html", help="output file (default: callscape.html)"
    )
    b.add_argument(
        "--max-body-lines",
        type=int,
        default=DEFAULT_MAX_BODY_LINES,
        metavar="N",
        help=f"show at most N lines of each definition (default: {DEFAULT_MAX_BODY_LINES})",
    )
    b.add_argument("--open", action="store_true", help="open the result in a browser")

    s = sub.add_parser("stats", help="print a summary of the call graph")
    _add_source_args(s)
    s.add_argument("--json", action="store_true", help="machine-readable output")

    for name, text in (("callers", "who calls a function"), ("callees", "what a function calls")):
        c = sub.add_parser(name, help=text)
        _add_source_args(c)
        c.add_argument("symbol", help="name, qualified name (Class.method) or file::name")
        c.add_argument(
            "--depth", type=int, default=1, help="how many levels to expand (default: 1)"
        )
        c.add_argument("--types", action="store_true", help="also follow type references")

    pa = sub.add_parser("path", help="shortest call chain from one function to another")
    _add_source_args(pa)
    pa.add_argument("source", help="the calling function")
    pa.add_argument("target", help="the function to reach")

    d = sub.add_parser("dot", help="export Graphviz DOT")
    _add_source_args(d)
    d.add_argument("--focus", metavar="SYMBOL", help="only the neighbourhood of this symbol")
    d.add_argument(
        "--depth", type=int, default=2, help="neighbourhood depth with --focus (default: 2)"
    )
    d.add_argument("--types", action="store_true", help="include type references")
    d.add_argument("-o", "--output", help="write to a file instead of stdout")

    j = sub.add_parser("json", help="export nodes and edges as JSON")
    _add_source_args(j)
    j.add_argument("-o", "--output", help="write to a file instead of stdout")
    return parser


def _load(args: argparse.Namespace) -> Graph:
    try:
        repo = load_repo(args.path, args.lang, args.exclude)
    except ScanError as exc:
        raise CliError(str(exc), EXIT_FAIL) from exc
    return Graph(repo)


def _pick(graph: Graph, query: str) -> Symbol:
    hits = graph.lookup(query)
    if not hits:
        raise CliError(f"no symbol matches {query!r}", EXIT_FAIL)
    if len(hits) > 1:
        shown = "\n".join(f"  {s.id}  ({s.kind}, line {s.line})" for s in hits[:12])
        more = f"\n  ... and {len(hits) - 12} more" if len(hits) > 12 else ""
        raise CliError(
            f"{query!r} is ambiguous, {len(hits)} symbols match. Use one of these ids:"
            f"\n{shown}{more}",
            EXIT_USAGE,
        )
    return hits[0]


def _out(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"wrote {output}", file=sys.stderr)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


# -- commands -----------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    if args.max_body_lines < 1:
        raise CliError("--max-body-lines must be at least 1", EXIT_USAGE)
    graph = _load(args)
    page = render_html(graph, args.max_body_lines)
    out = Path(args.output)
    try:
        out.write_text(page, encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write {out}: {exc.strerror or exc}", EXIT_FAIL) from exc
    st = graph.stats()
    print(
        f"callscape: {st['files']} files, {st['symbols']} symbols, {st['edges']} edges "
        f"({st['call_sites_resolved']} of {st['call_sites']} call sites resolved)"
    )
    for path, reason in graph.repo.skipped:
        print(f"skipped {path}: {reason}", file=sys.stderr)
    for path in st["files_with_syntax_errors"]:
        print(f"warning: syntax errors in {path}, parsed best-effort", file=sys.stderr)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return EXIT_OK


def cmd_stats(args: argparse.Namespace) -> int:
    graph = _load(args)
    st = graph.stats()
    if args.json:
        print(json.dumps(to_json(graph)["stats"], indent=2))
        return EXIT_OK
    sym = graph.symbol
    langs = ", ".join(f"{n} {k}" for k, n in st["files_by_language"].items())
    kinds = ", ".join(f"{n} {k}" for k, n in st["symbols_by_kind"].items())
    resolved, total = st["call_sites_resolved"], st["call_sites"]
    pct = f"{100 * resolved // total}%" if total else "n/a"
    print(f"files      {st['files']} ({langs})")
    print(f"symbols    {st['symbols']} ({kinds})")
    edge_kinds = ", ".join(f"{n} {k}" for k, n in st["edges_by_kind"].items())
    print(f"edges      {st['edges']} ({edge_kinds})")
    print(
        f"call sites {total}, {resolved} resolved to repo code ({pct}), "
        f"{st['call_sites_ambiguous']} ambiguous"
    )
    if st["files_with_syntax_errors"]:
        print(f"syntax errors in {len(st['files_with_syntax_errors'])} file(s)")
    print("\nmost called")
    for idx, n in st["most_called"][:8]:
        s = sym(idx)
        print(f"  {n:>4}  {s.qualname}  ({s.path}:{s.line})")
    print("\ncalls the most distinct functions")
    for idx, n in st["most_calling"][:8]:
        s = sym(idx)
        print(f"  {n:>4}  {s.qualname}  ({s.path}:{s.line})")
    entry = st["entry_points"]
    print(f"\nnever called from the repository: {len(entry)}")
    for idx in entry[:8]:
        s = sym(idx)
        print(f"  {s.qualname}  ({s.path}:{s.line})")
    cycles = st["cycles"]
    print(f"\ncall cycles: {len(cycles)}")
    for comp in cycles[:5]:
        names = [sym(i).qualname for i in comp]
        tail = f" +{len(names) - 6} more" if len(names) > 6 else ""
        print("  " + " <-> ".join(names[:6]) + tail)
    return EXIT_OK


def _print_tree(
    graph: Graph, root: Symbol, direction: str, depth: int, kinds: tuple[str, ...]
) -> int:
    count = 0

    def label(s: Symbol) -> str:
        return f"{s.qualname}  ({s.path}:{s.line})"

    def children(s: Symbol) -> list[Symbol]:
        found = (
            graph.callees(s.index, kinds) if direction == "out" else graph.callers(s.index, kinds)
        )
        return sorted(found, key=lambda x: (x.path, x.line))

    print(label(root))
    expanded: set[int] = {root.index}

    def walk(node: Symbol, prefix: str, level: int, path: tuple[int, ...]) -> None:
        nonlocal count
        kids = children(node)
        for i, kid in enumerate(kids):
            last = i == len(kids) - 1
            branch = "`-- " if last else "|-- "
            count += 1
            note = ""
            if kid.index in path:
                note = "  (cycle)"
            elif kid.index in expanded and level < depth and children(kid):
                note = "  (shown above)"
            print(f"{prefix}{branch}{label(kid)}{note}")
            if note or level >= depth:
                continue
            expanded.add(kid.index)
            walk(kid, prefix + ("    " if last else "|   "), level + 1, path + (kid.index,))

    walk(root, "", 1, (root.index,))
    return count


def cmd_relations(args: argparse.Namespace, direction: str) -> int:
    if args.depth < 1:
        raise CliError("--depth must be at least 1", EXIT_USAGE)
    graph = _load(args)
    root = _pick(graph, args.symbol)
    kinds = ALL_KINDS if args.types else CALL_KINDS
    n = _print_tree(graph, root, direction, args.depth, kinds)
    if n == 0:
        what = "calls nothing" if direction == "out" else "is not called"
        print(f"({root.qualname} {what} in this repository)", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


def cmd_path(args: argparse.Namespace) -> int:
    graph = _load(args)
    src = _pick(graph, args.source)
    dst = _pick(graph, args.target)
    chain = graph.shortest_path(src.index, dst.index)
    if chain is None:
        print(f"no call path from {src.qualname} to {dst.qualname}", file=sys.stderr)
        return EXIT_FAIL
    for step, idx in enumerate(chain):
        s = graph.symbol(idx)
        arrow = "" if step == 0 else "-> "
        print(f"{'  ' * min(step, 1)}{arrow}{s.qualname}  ({s.path}:{s.line})")
    print(f"{len(chain) - 1} call(s)")
    return EXIT_OK


def cmd_dot(args: argparse.Namespace) -> int:
    graph = _load(args)
    focus = _pick(graph, args.focus) if args.focus else None
    _out(to_dot(graph, focus=focus, depth=args.depth, types=args.types), args.output)
    return EXIT_OK


def cmd_json(args: argparse.Namespace) -> int:
    graph = _load(args)
    _out(json.dumps(to_json(graph), indent=2), args.output)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    try:
        if args.command == "build":
            return cmd_build(args)
        if args.command == "stats":
            return cmd_stats(args)
        if args.command in ("callers", "callees"):
            return cmd_relations(args, "in" if args.command == "callers" else "out")
        if args.command == "path":
            return cmd_path(args)
        if args.command == "dot":
            return cmd_dot(args)
        if args.command == "json":
            return cmd_json(args)
    except CliError as exc:
        print(f"callscape: {exc}", file=sys.stderr)
        return exc.code
    except BrokenPipeError:
        return EXIT_OK
    parser.error(f"unknown command {args.command!r}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
