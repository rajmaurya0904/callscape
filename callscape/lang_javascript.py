"""JavaScript extractor: functions, classes, methods, calls, requires and ES imports."""

from __future__ import annotations

import tree_sitter_javascript
from tree_sitter import Node

from .extract import (
    UNKNOWN_RECEIVER,
    Builder,
    Pushed,
    Scope,
    make_parser,
    same,
    simple_receiver,
    walk,
)
from .model import REF_CALL, REF_TYPE, REF_VALUE, FileIndex

_PARSER = None

_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_SELF = ("this",)


def _parser():
    global _PARSER
    if _PARSER is None:
        _PARSER = make_parser(tree_sitter_javascript.language())
    return _PARSER


def _string_value(b: Builder, node: Node | None) -> str:
    if node is None or node.type != "string":
        return ""
    return "".join(b.text(c) for c in node.named_children if c.type == "string_fragment")


class _JsHandler:
    def __init__(self, b: Builder) -> None:
        self.b = b

    def __call__(self, node: Node, scope: Scope) -> Pushed | None:
        kind = node.type
        if kind in ("function_declaration", "generator_function_declaration"):
            return self.function_declaration(node, scope)
        if kind in ("class_declaration", "class"):
            return self.klass(node, scope, node.child_by_field_name("name"))
        if kind == "method_definition":
            return self.method(node, scope)
        if kind == "field_definition":
            return self.field(node, scope)
        if kind == "variable_declarator":
            return self.declarator(node, scope)
        if kind == "assignment_expression":
            return self.assignment(node, scope)
        if kind == "pair":
            return self.pair(node, scope)
        if kind == "call_expression":
            return self.call(node, scope)
        if kind == "new_expression":
            return self.new(node, scope)
        if kind in ("jsx_self_closing_element", "jsx_opening_element"):
            self.jsx(node, scope)
            return None
        if kind == "import_statement":
            self.import_statement(node)
            return []
        return None

    # -- helpers --------------------------------------------------------------------

    def _is_default_export(self, node: Node) -> bool:
        parent = node.parent
        if parent is None or parent.type != "export_statement":
            return False
        return any(c.type == "default" for c in parent.children)

    def _define_function(
        self,
        node: Node,
        name: str,
        scope: Scope,
        *,
        value: Node | None = None,
        range_node: Node | None = None,
        qualname: str | None = None,
        kind: str | None = None,
    ) -> Pushed:
        b = self.b
        fn = value or node
        body = fn.child_by_field_name("body")
        if kind is None:
            kind = "method" if scope.kind in ("class", "object") and scope.prefix else "function"
        sym = b.add_symbol(
            node,
            name,
            kind,
            scope,
            range_node=range_node or node,
            signature=b.header(range_node or node, body),
            self_names=_SELF,
            cls=scope.cls,
            is_default_export=self._is_default_export(node),
            qualname=qualname,
        )
        inner = Scope(
            owner=sym.id, prefix=sym.qualname, kind="function", cls=scope.cls, self_names=_SELF
        )
        name_node = node.child_by_field_name("name")
        return [(c, inner) for c in fn.children if not same(c, name_node)]

    # -- definitions ----------------------------------------------------------------

    def function_declaration(self, node: Node, scope: Scope) -> Pushed:
        name = self.b.text(node.child_by_field_name("name"))
        return self._define_function(node, name, scope)

    def klass(self, node: Node, scope: Scope, name_node: Node | None) -> Pushed:
        b = self.b
        body = node.child_by_field_name("body")
        bases: list[str] = []
        heritage = next((c for c in node.children if c.type == "class_heritage"), None)
        heritage_nodes = list(heritage.named_children) if heritage is not None else []
        for h in heritage_nodes:
            if h.type in ("identifier", "member_expression"):
                bases.append("".join(b.text(h).split()))
        name = b.text(name_node) or "<anonymous>"
        sym = b.add_symbol(
            node,
            name,
            "class",
            scope,
            range_node=node,
            signature=b.header(node, body),
            bases=bases,
            is_default_export=self._is_default_export(node),
        )
        for h in heritage_nodes:
            if h.type == "identifier":
                b.add_ref(h, sym.id, b.text(h), REF_TYPE)
            elif h.type == "member_expression":
                self.member_ref(h, sym.id, REF_TYPE)
        inner = Scope(owner=sym.id, prefix=sym.qualname, kind="class", cls=sym.qualname)
        extra = [(c, inner) for c in heritage_nodes if c.type == "call_expression"]
        return ([(body, inner)] if body is not None else []) + extra

    def method(self, node: Node, scope: Scope) -> Pushed:
        name_node = node.child_by_field_name("name")
        if name_node is None or name_node.type == "computed_property_name":
            return [(c, scope) for c in node.children]
        name = self.b.text(name_node)
        return self._define_function(node, name, scope)

    def field(self, node: Node, scope: Scope) -> Pushed | None:
        value = node.child_by_field_name("value")
        name_node = node.child_by_field_name("property")
        if value is not None and value.type in _FUNCTION_VALUES and name_node is not None:
            return self._define_function(
                node, self.b.text(name_node), scope, value=value, range_node=node
            )
        return None

    def declarator(self, node: Node, scope: Scope) -> Pushed | None:
        b = self.b
        name_node = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if value is None:
            return None
        if value.type == "call_expression" and self._require(value) is not None:
            self.bind_require(name_node, self._require(value))
            return []
        if name_node is None or name_node.type != "identifier":
            return None
        name = b.text(name_node)
        decl = (
            node.parent
            if node.parent
            and node.parent.type
            in (
                "lexical_declaration",
                "variable_declaration",
            )
            else node
        )
        range_node = decl
        if decl.parent is not None and decl.parent.type == "export_statement":
            range_node = decl.parent
        if value.type in _FUNCTION_VALUES:
            return self._define_function(node, name, scope, value=value, range_node=range_node)
        if value.type == "class":
            return self.klass_value(node, name, value, scope, range_node)
        if value.type == "object":
            inner = Scope(owner=scope.owner, prefix=name, kind="object", cls=name)
            return [(c, inner) for c in value.children]
        return None

    def klass_value(
        self, node: Node, name: str, value: Node, scope: Scope, range_node: Node
    ) -> Pushed:
        b = self.b
        body = value.child_by_field_name("body")
        sym = b.add_symbol(
            node, name, "class", scope, range_node=range_node, signature=b.header(range_node, body)
        )
        inner = Scope(owner=sym.id, prefix=sym.qualname, kind="class", cls=sym.qualname)
        return [(body, inner)] if body is not None else []

    def assignment(self, node: Node, scope: Scope) -> Pushed | None:
        b = self.b
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or left.type != "member_expression":
            return None
        obj = b.text(left.child_by_field_name("object"))
        prop = left.child_by_field_name("property")
        if prop is None:
            return None
        name = b.text(prop)
        stmt = node.parent if node.parent and node.parent.type == "expression_statement" else node
        if right.type in _FUNCTION_VALUES:
            if obj.endswith(".prototype"):
                owner_cls = obj[: -len(".prototype")]
                inner_scope = Scope(
                    owner=scope.owner, prefix=owner_cls, kind="class", cls=owner_cls
                )
                return self._define_function(
                    node, name, inner_scope, value=right, range_node=stmt, kind="method"
                )
            top = Scope(owner=scope.owner, prefix=scope.prefix, kind=scope.kind, cls=scope.cls)
            return self._define_function(
                node, name, top, value=right, range_node=stmt, kind="function"
            )
        if b.text(left) == "module.exports" and right.type == "object":
            inner = Scope(owner=scope.owner, prefix="", kind="object")
            return [(c, inner) for c in right.children]
        return None

    def pair(self, node: Node, scope: Scope) -> Pushed | None:
        value = node.child_by_field_name("value")
        key = node.child_by_field_name("key")
        if (
            value is not None
            and key is not None
            and value.type in _FUNCTION_VALUES
            and key.type in ("property_identifier", "identifier", "string")
        ):
            name = _string_value(self.b, key) if key.type == "string" else self.b.text(key)
            if name:
                return self._define_function(node, name, scope, value=value, range_node=node)
        return None

    # -- references -----------------------------------------------------------------

    def member_ref(self, node: Node, owner: str, kind: str) -> None:
        b = self.b
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        if prop is None:
            return
        receiver = UNKNOWN_RECEIVER
        if obj is not None and obj.type in ("identifier", "this", "super", "member_expression"):
            receiver = simple_receiver(b.text(obj))
        b.add_ref(prop, owner, b.text(prop), kind, receiver)

    def _require(self, call: Node) -> str | None:
        fn = call.child_by_field_name("function")
        args = call.child_by_field_name("arguments")
        if fn is None or fn.type != "identifier" or self.b.text(fn) != "require" or args is None:
            return None
        if not args.named_children:
            return None
        spec = _string_value(self.b, args.named_children[0])
        return spec or None

    def bind_require(self, name_node: Node | None, spec: str | None) -> None:
        b = self.b
        if name_node is None or spec is None:
            return
        if name_node.type == "identifier":
            b.add_import(b.text(name_node), spec)
        elif name_node.type == "object_pattern":
            for child in name_node.named_children:
                if child.type == "shorthand_property_identifier_pattern":
                    n = b.text(child)
                    b.add_import(n, spec, n)
                elif child.type == "pair_pattern":
                    key = b.text(child.child_by_field_name("key"))
                    val = child.child_by_field_name("value")
                    if val is not None and val.type == "identifier":
                        b.add_import(b.text(val), spec, key)

    def call(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        skip: Node | None = None
        if fn is not None:
            if fn.type == "identifier":
                b.add_ref(fn, scope.owner, b.text(fn), REF_CALL)
                skip = fn
            elif fn.type == "super":
                b.add_ref(fn, scope.owner, "constructor", REF_CALL, "super")
                skip = fn
            elif fn.type == "member_expression":
                self.member_ref(fn, scope.owner, REF_CALL)
                skip = fn
        if args is not None:
            for arg in args.named_children:
                if arg.type == "identifier":
                    b.add_ref(arg, scope.owner, b.text(arg), REF_VALUE)
                elif arg.type == "member_expression":
                    self.member_ref(arg, scope.owner, REF_VALUE)
        pushed: list[tuple[Node, Scope]] = []
        for child in node.children:
            if same(child, skip):
                if child.type == "member_expression":
                    obj = child.child_by_field_name("object")
                    if obj is not None and obj.type not in ("identifier", "this", "super"):
                        pushed.append((obj, scope))
                continue
            pushed.append((child, scope))
        return pushed

    def new(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        ctor = node.child_by_field_name("constructor")
        skip: Node | None = None
        if ctor is not None and ctor.type == "identifier":
            b.add_ref(ctor, scope.owner, b.text(ctor), REF_CALL)
            skip = ctor
        elif ctor is not None and ctor.type == "member_expression":
            self.member_ref(ctor, scope.owner, REF_CALL)
            skip = ctor
        return [(c, scope) for c in node.children if c is not skip]

    def jsx(self, node: Node, scope: Scope) -> None:
        name = node.child_by_field_name("name")
        if name is not None and name.type == "identifier":
            text = self.b.text(name)
            if text[:1].isupper():
                self.b.add_ref(name, scope.owner, text, REF_CALL)

    # -- imports --------------------------------------------------------------------

    def import_statement(self, node: Node) -> None:
        b = self.b
        spec = _string_value(b, node.child_by_field_name("source"))
        if not spec:
            return
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for part in clause.named_children:
                if part.type == "identifier":
                    b.add_import(b.text(part), spec, "default")
                elif part.type == "namespace_import":
                    ident = next((c for c in part.named_children if c.type == "identifier"), None)
                    if ident is not None:
                        b.add_import(b.text(ident), spec)
                elif part.type == "named_imports":
                    for item in part.named_children:
                        if item.type != "import_specifier":
                            continue
                        name = b.text(item.child_by_field_name("name"))
                        alias = item.child_by_field_name("alias")
                        b.add_import(b.text(alias) if alias is not None else name, spec, name)


def extract(path: str, data: bytes) -> FileIndex:
    b = Builder(path, "javascript", data)
    tree = _parser().parse(data)
    b.index.has_error = tree.root_node.has_error
    walk(tree.root_node, Scope(owner=b.module_id), _JsHandler(b))
    return b.finish()
