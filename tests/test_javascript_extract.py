from __future__ import annotations

from callscape.lang_javascript import extract

SOURCE = b"""import { render as draw, Widget } from './ui.js';
import Default from './default.js';
import * as ns from './ns.js';
const util = require('./util');
const { pick, other: renamed } = require('./picker');

export default function boot() {
  draw(this);
  new Panel().open();
  ns.go(1, callback);
}

class Panel extends Widget {
  constructor() { super(); }
  static make() { return new Panel(); }
  open() { this.paint(); super.open(); util.log('x'); }
  handler = () => { later(); };
}

const arrow = (x) => { helper(x); };
exports.exported = function () { one(); };
Panel.prototype.legacy = function () { this.open(); };
const table = { run() { this.stop(); }, stop: () => 1 };
module.exports = { alpha() { beta(); } };
function view() { return <Panel />; }
top();
"""


def by_qual(index):
    return {s.qualname: s for s in index.symbols}


def test_symbols_and_kinds() -> None:
    syms = by_qual(extract("a.js", SOURCE))
    assert syms["boot"].kind == "function"
    assert syms["Panel"].kind == "class"
    assert syms["Panel.constructor"].kind == "method"
    assert syms["Panel.make"].kind == "method"
    assert syms["Panel.handler"].kind == "method"
    assert syms["arrow"].kind == "function"
    assert syms["exported"].kind == "function"
    assert syms["Panel.legacy"].kind == "method"
    assert syms["table.run"].kind == "method"
    assert syms["table.stop"].kind == "method"
    assert syms["alpha"].kind == "function"


def test_default_export_is_flagged() -> None:
    syms = by_qual(extract("a.js", SOURCE))
    assert syms["boot"].is_default_export
    assert not syms["arrow"].is_default_export


def test_class_heritage_becomes_base_and_type_ref() -> None:
    index = extract("a.js", SOURCE)
    assert by_qual(index)["Panel"].bases == ["Widget"]
    assert any(r.kind == "type" and r.name == "Widget" for r in index.refs)


def test_calls_with_receivers() -> None:
    index = extract("a.js", SOURCE)
    calls = {(r.owner.split("::")[1], r.receiver, r.name) for r in index.refs if r.kind == "call"}
    assert ("boot", None, "draw") in calls
    assert ("boot", None, "Panel") in calls  # new Panel()
    assert ("boot", "ns", "go") in calls
    assert ("Panel.open", "this", "paint") in calls
    assert ("Panel.open", "util", "log") in calls
    assert ("Panel.constructor", "super", "constructor") in calls
    assert ("Panel.open", "super", "open") in calls
    assert ("Panel.handler", None, "later") in calls
    assert ("table.run", "this", "stop") in calls
    assert ("alpha", None, "beta") in calls
    assert ("<module>", None, "top") in calls


def test_call_on_a_call_result_has_unknown_receiver() -> None:
    index = extract("a.js", SOURCE)
    ref = next(r for r in index.refs if r.name == "open" and r.owner.endswith("::boot"))
    assert ref.receiver == "?"


def test_jsx_component_use_is_a_call() -> None:
    index = extract("a.js", SOURCE)
    assert any(r.owner.endswith("::view") and r.name == "Panel" for r in index.refs)


def test_callbacks_passed_by_name_are_references() -> None:
    index = extract("a.js", SOURCE)
    assert any(r.kind == "ref" and r.name == "callback" for r in index.refs)


def test_imports_and_requires() -> None:
    imports = {i.local: (i.target, i.name) for i in extract("a.js", SOURCE).imports}
    assert imports["draw"] == ("./ui.js", "render")
    assert imports["Widget"] == ("./ui.js", "Widget")
    assert imports["Default"] == ("./default.js", "default")
    assert imports["ns"] == ("./ns.js", None)
    assert imports["util"] == ("./util", None)
    assert imports["pick"] == ("./picker", "pick")
    assert imports["renamed"] == ("./picker", "other")


def test_prototype_assignment_is_a_method_of_the_class() -> None:
    legacy = by_qual(extract("a.js", SOURCE))["Panel.legacy"]
    assert legacy.cls == "Panel"
    assert legacy.parent == "Panel"


def test_signature_of_arrow_function_assignment() -> None:
    assert by_qual(extract("a.js", SOURCE))["arrow"].signature == "const arrow = (x) =>"


def test_column_offsets_point_at_the_identifier() -> None:
    index = extract("a.js", SOURCE)
    ref = next(r for r in index.refs if r.name == "later")
    assert index.lines[ref.line - 1][ref.col : ref.end_col] == "later"


def test_template_literals_with_substitutions_do_not_break_parsing() -> None:
    lines = [
        "export async function q() {",
        "  const data = await evaluate(`",
        "    (function(){ return ${X}; })()",
        "  `);",
        "  return data;",
        "}",
    ]
    index = extract("t.js", "\n".join(lines).encode())
    assert [s.qualname for s in index.symbols] == ["q"]
    assert any(r.name == "evaluate" for r in index.refs)
