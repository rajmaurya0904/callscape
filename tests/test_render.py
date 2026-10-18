from __future__ import annotations

import json
import re
from pathlib import Path

from callscape.graph import Graph
from callscape.render import build_payload, render_html
from callscape.repo import load_repo


def embedded_payload(html: str) -> dict:
    match = re.search(
        r'<script id="callscape-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match, "payload script element not found"
    return json.loads(match.group(1))


def test_page_is_self_contained(graph: Graph) -> None:
    html = render_html(graph)
    assert html.startswith("<!doctype html>")
    assert "http://" not in re.sub(r"http://www\.w3\.org/2000/svg", "", html)
    assert "https://" not in html
    assert "<link" not in html
    assert "__DATA__" not in html
    assert "/*__JS__*/" not in html
    assert "/*__CSS__*/" not in html


def test_payload_round_trips_through_the_page(graph: Graph) -> None:
    payload = embedded_payload(render_html(graph))
    assert len(payload["syms"]) == len(graph.repo.symbols)
    assert [f["p"] for f in payload["files"]] == sorted(graph.repo.files)


def test_title_names_the_repository(graph: Graph) -> None:
    assert "<title>callscape: sample</title>" in render_html(graph)


def test_edge_lists_mirror_the_graph(graph: Graph) -> None:
    payload = build_payload(graph)
    run = graph.repo.by_id["pkg/core.py::Engine.run"].index
    sym = payload["syms"][run]
    out_targets = {payload["syms"][o[0]]["q"] for o in sym["o"]}
    assert {"Engine.step", "Base.start", "log"} <= out_targets
    callers = {payload["syms"][c[0]]["q"] for c in sym["c"]}
    assert callers == {"main"}


def test_reference_spans_cover_exactly_the_identifier(graph: Graph) -> None:
    payload = build_payload(graph)
    checked = 0
    for sym in payload["syms"]:
        lines = sym["b"].split("\n")
        for rel, start, end, _targets, kind, _amb in sym["r"]:
            text = lines[rel][start:end]
            assert text.isidentifier()
            assert kind in ("c", "r", "t")
            checked += 1
    assert checked > 20


def test_members_list_methods_of_a_class(graph: Graph) -> None:
    payload = build_payload(graph)
    engine = graph.repo.by_id["pkg/core.py::Engine"].index
    members = {payload["syms"][m]["q"] for m in payload["syms"][engine]["m"]}
    assert members == {"Engine.__init__", "Engine.run", "Engine.step"}


def test_go_methods_in_another_file_are_members_of_the_type(tmp_path: Path) -> None:
    (tmp_path / "a.go").write_text("package p\n\ntype T struct{}\n", encoding="utf-8")
    (tmp_path / "b.go").write_text("package p\n\nfunc (t *T) Do() {}\n", encoding="utf-8")
    payload = build_payload(Graph(load_repo(tmp_path)))
    t = next(s for s in payload["syms"] if s["q"] == "T")
    assert [payload["syms"][m]["q"] for m in t["m"]] == ["T.Do"]


def test_long_bodies_are_truncated_with_a_flag(tmp_path: Path) -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(50))
    (tmp_path / "big.py").write_text(f"def big():\n{body}\n", encoding="utf-8")
    payload = build_payload(Graph(load_repo(tmp_path)), max_body_lines=10)
    sym = payload["syms"][0]
    assert sym["t"] == 1
    assert len(sym["b"].split("\n")) == 10


def test_source_containing_script_end_tag_cannot_break_out(tmp_path: Path) -> None:
    (tmp_path / "x.js").write_text(
        'function f() { return "</script><script>alert(1)</script><!--"; }\n', encoding="utf-8"
    )
    html = render_html(Graph(load_repo(tmp_path)))
    payload = embedded_payload(html)
    assert "</script><script>alert(1)" in payload["syms"][0]["b"]
    assert html.count("</script>") == 2  # data element and viewer script only
    assert "<script>alert(1)" not in html


def test_markers_inside_user_source_are_not_substituted(tmp_path: Path) -> None:
    marker = "__TITLE__ /*__JS__*/ __DATA__"
    source = 'def f():\n    return "' + marker + '"\n'
    (tmp_path / "x.py").write_text(source, encoding="utf-8")
    payload = embedded_payload(render_html(Graph(load_repo(tmp_path))))
    assert marker in payload["syms"][0]["b"]


def test_non_ascii_source_survives(tmp_path: Path) -> None:
    (tmp_path / "u.py").write_text("def grüße():\n    return 'héllo ✓'\n", encoding="utf-8")
    payload = embedded_payload(render_html(Graph(load_repo(tmp_path))))
    assert payload["syms"][0]["n"] == "grüße"
    assert "héllo ✓" in payload["syms"][0]["b"]
