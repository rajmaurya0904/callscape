from __future__ import annotations

from pathlib import Path

from callscape.graph import Graph
from callscape.repo import load_repo

from .conftest import edge_targets


def targets(graph: Graph, caller: str) -> set[str]:
    return edge_targets(graph, caller)


def test_self_calls_resolve_to_methods_of_the_same_class(graph: Graph) -> None:
    assert "pkg/core.py::Engine.step" in targets(graph, "pkg/core.py::Engine.run")


def test_self_calls_follow_inheritance(graph: Graph) -> None:
    assert "pkg/core.py::Base.start" in targets(graph, "pkg/core.py::Engine.run")


def test_calling_a_class_reaches_its_constructor(graph: Graph) -> None:
    out = targets(graph, "pkg/core.py::make")
    assert "pkg/core.py::Engine" in out
    assert "pkg/core.py::Engine.__init__" in out


def test_from_import_with_alias(graph: Graph) -> None:
    assert "pkg/helpers.py::slugify" in targets(graph, "pkg/core.py::Engine.__init__")


def test_relative_module_import_attribute_call(graph: Graph) -> None:
    out = targets(graph, "pkg/core.py::Engine.run")
    assert "pkg/helpers.py::log" in out


def test_import_through_a_package_reexport(graph: Graph) -> None:
    # main.py does `from pkg import Engine`; pkg/__init__.py re-exports it from .core.
    assert "pkg/core.py::Engine" in targets(graph, "main.py::main")


def test_module_level_calls_belong_to_the_module_symbol(graph: Graph) -> None:
    assert "main.py::main" in targets(graph, "main.py::<module>")


def test_calls_into_the_standard_library_are_not_resolved(graph: Graph) -> None:
    unresolved = {
        (r.receiver, r.name) for r in graph.repo.refs if r.kind == "call" and not r.targets
    }
    assert ("os", "getcwd") in unresolved
    assert (None, "print") in unresolved


def test_method_call_on_a_local_variable_uses_the_unique_method_name(graph: Graph) -> None:
    # e = make(); e.run(...) -> the only method named run in Python files.
    assert "pkg/core.py::Engine.run" in targets(graph, "main.py::main")


def test_js_named_import_and_super(graph: Graph) -> None:
    out = targets(graph, "web/app.js::App.start")
    assert "web/app.js::App.draw" in out  # this.draw()
    assert "web/ui.js::Widget.start" in out  # super.start()


def test_js_require_binding_resolves_member_calls(graph: Graph) -> None:
    assert "web/util.js::log" in targets(graph, "web/app.js::App.start")


def test_js_imported_function(graph: Graph) -> None:
    assert "web/ui.js::render" in targets(graph, "web/app.js::App.draw")


def test_js_object_literal_method_resolves_sibling_function(graph: Graph) -> None:
    assert "web/util.js::fmt" in targets(graph, "web/util.js::log")


def test_go_package_qualified_call_through_go_mod(graph: Graph) -> None:
    assert "goapp/util/util.go::Log" in targets(graph, "goapp/main.go::Server.Run")


def test_go_promoted_method_through_embedded_struct(graph: Graph) -> None:
    assert "goapp/main.go::Base.Ping" in targets(graph, "goapp/main.go::Server.Run")


def test_go_same_package_function(graph: Graph) -> None:
    assert "goapp/main.go::helper" in targets(graph, "goapp/main.go::Server.handle")


def test_go_struct_uses_imported_type(graph: Graph) -> None:
    kinds = {
        (e.kind, graph.symbol(e.dst).id)
        for e in graph.out[graph.repo.by_id["goapp/main.go::Server"].index]
    }
    assert ("type", "goapp/util/util.go::Config") in kinds
    assert ("type", "goapp/main.go::Base") in kinds


def test_calls_across_languages_never_mix(graph: Graph) -> None:
    for ref in graph.repo.refs:
        owner = graph.repo.by_id[ref.owner]
        for t in ref.targets:
            assert graph.repo.by_id[t].lang == owner.lang


def test_ambiguity_is_flagged_when_several_methods_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "class A:\n    def go(self): pass\n\nclass B:\n    def go(self): pass\n\n"
        "def use(x):\n    x.go()\n",
        encoding="utf-8",
    )
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "go" and r.kind == "call")
    assert sorted(ref.targets) == ["a.py::A.go", "a.py::B.go"]
    assert ref.ambiguous


def test_too_many_candidates_means_unresolved(tmp_path: Path) -> None:
    classes = "\n".join(f"class C{i}:\n    def tick(self): pass\n" for i in range(6))
    (tmp_path / "a.py").write_text(classes, encoding="utf-8")
    (tmp_path / "b.py").write_text("def use(x):\n    x.tick()\n", encoding="utf-8")
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "tick")
    assert ref.targets == []


def test_ubiquitous_method_names_do_not_cross_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("class Store:\n    def get(self): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def use(d):\n    d.get()\n", encoding="utf-8")
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "get")
    assert ref.targets == []


def test_nested_function_shadows_module_level_name(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def helper(): pass\n\ndef outer():\n    def helper(): pass\n    helper()\n",
        encoding="utf-8",
    )
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "helper" and r.kind == "call")
    assert ref.targets == ["a.py::outer.helper"]


def test_class_attribute_names_are_not_visible_as_bare_names(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "class A:\n    def helper(self): pass\n    def other(self):\n        helper()\n",
        encoding="utf-8",
    )
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "helper" and r.kind == "call")
    assert ref.targets == []


def test_python_submodule_attribute_call(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "lib" / "util.py").write_text("def work(): pass\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import lib.util\n\ndef go():\n    lib.util.work()\n", encoding="utf-8"
    )
    repo = load_repo(tmp_path)
    ref = next(r for r in repo.refs if r.name == "work")
    assert ref.targets == ["lib/util.py::work"]
