from __future__ import annotations

from callscape.lang_go import extract

SOURCE = b"""package server

import (
	"fmt"
	str "strings"
	"example.com/app/util"
	_ "embed"
)

type Base struct{}

type Server struct {
	Base
	*Logger
	util.Config
	Name string
}

type Handler interface {
	Serve(req Request) Response
}

type ID = int

type (
	Alpha struct{}
	Beta  int
)

func (s *Server) Run(req Request) util.Result {
	s.handle()
	fmt.Println(len("x"))
	run := func() { inner() }
	go worker()
	register(s.handle)
	return Server{}
}

func (s *Server) handle() {}

func New() *Server { return &Server{} }
"""


def by_qual(index):
    return {s.qualname: s for s in index.symbols}


def test_package_name_is_recorded() -> None:
    assert extract("s.go", SOURCE).package == "server"


def test_symbol_kinds() -> None:
    syms = by_qual(extract("s.go", SOURCE))
    assert syms["Server"].kind == "struct"
    assert syms["Handler"].kind == "interface"
    assert syms["ID"].kind == "type"
    assert syms["Alpha"].kind == "struct"
    assert syms["Beta"].kind == "type"
    assert syms["New"].kind == "function"
    assert syms["Server.Run"].kind == "method"


def test_embedded_fields_become_bases() -> None:
    assert by_qual(extract("s.go", SOURCE))["Server"].bases == ["Base", "Logger", "util.Config"]


def test_method_receiver_is_recorded() -> None:
    run = by_qual(extract("s.go", SOURCE))["Server.Run"]
    assert run.cls == "Server"
    assert run.parent == "Server"
    assert run.self_names == ("s",)
    assert run.signature == "func (s *Server) Run(req Request) util.Result"


def test_grouped_type_declarations_get_their_own_range() -> None:
    syms = by_qual(extract("s.go", SOURCE))
    assert syms["Alpha"].line == syms["Alpha"].end_line
    assert syms["Alpha"].line != syms["Beta"].line


def test_calls_skip_builtins_and_include_closures() -> None:
    index = extract("s.go", SOURCE)
    calls = {(r.receiver, r.name) for r in index.refs if r.kind == "call"}
    assert ("s", "handle") in calls
    assert ("fmt", "Println") in calls
    assert (None, "inner") in calls  # inside a func literal
    assert (None, "worker") in calls  # go statement
    assert (None, "len") not in calls


def test_method_values_passed_as_arguments_are_references() -> None:
    index = extract("s.go", SOURCE)
    assert any(r.kind == "ref" and r.receiver == "s" and r.name == "handle" for r in index.refs)


def test_type_references_include_qualified_types() -> None:
    index = extract("s.go", SOURCE)
    types = {(r.receiver, r.name) for r in index.refs if r.kind == "type"}
    assert (None, "Request") in types
    assert ("util", "Result") in types
    assert (None, "string") not in types


def test_imports_use_alias_or_last_segment() -> None:
    imports = {i.local: i.target for i in extract("s.go", SOURCE).imports}
    assert imports == {
        "fmt": "fmt",
        "str": "strings",
        "util": "example.com/app/util",
    }


def test_definition_names_are_not_counted_as_references() -> None:
    index = extract("s.go", SOURCE)
    own = [r for r in index.refs if r.owner.endswith("::Alpha") and r.name == "Alpha"]
    assert own == []
