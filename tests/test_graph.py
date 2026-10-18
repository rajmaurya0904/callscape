from __future__ import annotations

from callscape.graph import ALL_KINDS, Graph


def idx(graph: Graph, symbol_id: str) -> int:
    return graph.repo.by_id[symbol_id].index


def ids(symbols) -> set[str]:
    return {s.id for s in symbols}


def test_callers_and_callees_are_inverse(graph: Graph) -> None:
    for sym in graph.repo.symbols:
        for callee in graph.callees(sym.index):
            assert sym.id in ids(graph.callers(callee.index))


def test_callers_lists_each_caller_once(graph: Graph) -> None:
    fmt = idx(graph, "pkg/helpers.py::fmt")
    assert ids(graph.callers(fmt)) == {"pkg/core.py::Engine.step", "pkg/helpers.py::log"}


def test_edge_counts_and_lines_are_aggregated(graph: Graph) -> None:
    main = idx(graph, "main.py::main")
    run = idx(graph, "pkg/core.py::Engine.run")
    edge = next(e for e in graph.out[main] if e.dst == run)
    assert edge.count == 2
    assert len(edge.lines) == 2


def test_type_edges_are_separate_from_call_edges(graph: Graph) -> None:
    server = idx(graph, "goapp/main.go::Server")
    assert graph.callees(server) == []
    assert "goapp/util/util.go::Config" in ids(graph.callees(server, ALL_KINDS))


def test_lookup_tiers(graph: Graph) -> None:
    assert ids(graph.lookup("pkg/core.py::Engine.run")) == {"pkg/core.py::Engine.run"}
    assert ids(graph.lookup("Engine.run")) == {"pkg/core.py::Engine.run"}
    assert ids(graph.lookup("slugify")) == {"pkg/helpers.py::slugify"}
    assert ids(graph.lookup("helpers.py::fmt")) == {"pkg/helpers.py::fmt"}
    assert "pkg/core.py::Engine.run" in ids(graph.lookup("engine.ru"))
    assert graph.lookup("does_not_exist") == []


def test_lookup_reports_every_match_for_an_ambiguous_name(graph: Graph) -> None:
    assert ids(graph.lookup("fmt")) == {"pkg/helpers.py::fmt", "web/util.js::fmt"}


def test_lookup_normalises_windows_separators(graph: Graph) -> None:
    assert ids(graph.lookup(r"pkg\core.py::make")) == {"pkg/core.py::make"}


def test_reachable_respects_depth(graph: Graph) -> None:
    main = idx(graph, "main.py::main")
    one = graph.reachable(main, "out", 1)
    deep = graph.reachable(main, "out")
    assert set(one) < set(deep)
    assert max(one.values()) == 1
    assert idx(graph, "pkg/helpers.py::fmt") in deep
    assert idx(graph, "pkg/helpers.py::fmt") not in one


def test_reachable_in_direction_finds_callers(graph: Graph) -> None:
    fmt = idx(graph, "pkg/helpers.py::fmt")
    upstream = graph.reachable(fmt, "in")
    assert idx(graph, "main.py::main") in upstream
    assert idx(graph, "main.py::<module>") in upstream


def test_shortest_path(graph: Graph) -> None:
    path = graph.shortest_path(idx(graph, "main.py::main"), idx(graph, "pkg/helpers.py::fmt"))
    assert path is not None
    names = [graph.symbol(i).id for i in path]
    assert names[0] == "main.py::main"
    assert names[-1] == "pkg/helpers.py::fmt"
    assert len(names) == 4


def test_no_path_between_unconnected_languages(graph: Graph) -> None:
    assert graph.shortest_path(idx(graph, "main.py::main"), idx(graph, "web/app.js::boot")) is None


def test_path_to_self_is_trivial(graph: Graph) -> None:
    i = idx(graph, "main.py::main")
    assert graph.shortest_path(i, i) == [i]


def test_mutual_recursion_is_reported_as_a_cycle(graph: Graph) -> None:
    cycles = [{graph.symbol(i).id for i in c} for c in graph.cycles()]
    assert {"pkg/helpers.py::is_even", "pkg/helpers.py::is_odd"} in cycles


def test_direct_recursion_is_reported_separately(graph: Graph) -> None:
    assert idx(graph, "pkg/helpers.py::fact") in graph.recursive()


def test_stats_are_consistent(graph: Graph) -> None:
    st = graph.stats()
    assert st["files"] == 9
    assert st["files_by_language"] == {"go": 2, "javascript": 3, "python": 4}
    assert st["call_sites_resolved"] <= st["call_sites"]
    assert st["edges"] == sum(st["edges_by_kind"].values())
    assert st["files_with_syntax_errors"] == []


def test_entry_points_have_no_callers(graph: Graph) -> None:
    st = graph.stats()
    assert graph.symbol(st["entry_points"][0]).kind in ("function", "method")
    for i in st["entry_points"]:
        assert graph.fan_in(i) == 0
    assert idx(graph, "goapp/main.go::main") in st["entry_points"]
