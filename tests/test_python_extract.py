from __future__ import annotations

from callscape.lang_python import extract

SOURCE = b'''import os
import a.b as ab
from . import sibling
from ..pkg.mod import thing as renamed, other


@decorator
class Child(Base, mixins.Mixin):
    """Does child things.

    More text.
    """

    def method(self, x: Item = None) -> Result:
        self.helper()
        free_function(map(callback, [1]))
        ab.run()
        return os.getcwd()

    @staticmethod
    def helper():
        def inner():
            deep()
        inner()


def free_function(fn):
    pass


free_function(len)
'''


def by_qual(index):
    return {s.qualname: s for s in index.symbols}


def test_symbols_and_kinds() -> None:
    index = extract("m.py", SOURCE)
    syms = by_qual(index)
    assert syms["Child"].kind == "class"
    assert syms["Child.method"].kind == "method"
    assert syms["Child.helper"].kind == "method"
    assert syms["Child.helper.inner"].kind == "function"
    assert syms["free_function"].kind == "function"
    assert syms["<module>"].kind == "module"


def test_decorators_are_part_of_the_range() -> None:
    syms = by_qual(extract("m.py", SOURCE))
    assert syms["Child"].body_start == 7
    assert syms["Child"].line == 8
    assert syms["Child.helper"].body_start == syms["Child.helper"].line - 1


def test_end_line_covers_the_whole_body() -> None:
    syms = by_qual(extract("m.py", SOURCE))
    assert syms["Child"].end_line == 24
    assert syms["Child.helper.inner"].end_line == 23


def test_signature_and_docstring() -> None:
    syms = by_qual(extract("m.py", SOURCE))
    assert syms["Child.method"].signature == "def method(self, x: Item = None) -> Result:"
    assert syms["Child"].doc == "Does child things."


def test_bases_include_dotted_names() -> None:
    assert by_qual(extract("m.py", SOURCE))["Child"].bases == ["Base", "mixins.Mixin"]


def test_calls_record_receivers() -> None:
    refs = extract("m.py", SOURCE).refs
    calls = {(r.owner.split("::")[1], r.receiver, r.name) for r in refs if r.kind == "call"}
    assert ("Child.method", "self", "helper") in calls
    assert ("Child.method", None, "free_function") in calls
    assert ("Child.method", "ab", "run") in calls
    assert ("Child.method", "os", "getcwd") in calls
    assert ("Child.helper.inner", None, "deep") in calls
    assert ("Child.helper", None, "inner") in calls


def test_functions_passed_as_values_are_references() -> None:
    refs = extract("m.py", SOURCE).refs
    values = {(r.owner.split("::")[1], r.name) for r in refs if r.kind == "ref"}
    assert ("Child.method", "callback") in values
    assert ("<module>", "len") in values


def test_type_references_from_annotations_and_bases() -> None:
    refs = extract("m.py", SOURCE).refs
    types = {(r.owner.split("::")[1], r.receiver, r.name) for r in refs if r.kind == "type"}
    assert ("Child.method", None, "Item") in types
    assert ("Child.method", None, "Result") in types
    assert ("Child", None, "Base") in types
    assert ("Child", "mixins", "Mixin") in types


def test_ref_columns_point_at_the_name() -> None:
    index = extract("m.py", SOURCE)
    ref = next(r for r in index.refs if r.name == "helper" and r.receiver == "self")
    line = index.lines[ref.line - 1]
    assert line[ref.col : ref.end_col] == "helper"


def test_imports() -> None:
    imports = {i.local: (i.target, i.name) for i in extract("m.py", SOURCE).imports}
    assert imports["os"] == ("os", None)
    assert imports["ab"] == ("a.b", None)
    assert imports["sibling"] == (".", "sibling")
    assert imports["renamed"] == ("..pkg.mod", "thing")
    assert imports["other"] == ("..pkg.mod", "other")


def test_module_symbol_only_when_top_level_code_calls_something() -> None:
    quiet = extract("q.py", b"def f():\n    pass\n")
    assert all(s.kind != "module" for s in quiet.symbols)


def test_unicode_columns_are_character_offsets() -> None:
    index = extract("u.py", "def f():\n    s = 'héllo ✓'; go()\n".encode())
    ref = next(r for r in index.refs if r.name == "go")
    assert index.lines[ref.line - 1][ref.col : ref.end_col] == "go"


def test_syntax_errors_are_flagged_but_parsing_continues() -> None:
    index = extract("bad.py", b"def ok():\n    run()\n\ndef broken(:\n    pass\n")
    assert index.has_error
    assert any(s.name == "ok" for s in index.symbols)


def test_crlf_line_endings_do_not_leak_into_lines() -> None:
    index = extract("w.py", b"def f():\r\n    go()\r\n")
    assert index.lines[0] == "def f():"
