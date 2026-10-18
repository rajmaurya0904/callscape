"""Python extractor: definitions, calls, type references and imports."""

from __future__ import annotations

import tree_sitter_python
from tree_sitter import Node

from .extract import (
    UNKNOWN_RECEIVER,
    Builder,
    Pushed,
    Scope,
    dedent_first_line,
    make_parser,
    same,
    simple_receiver,
    walk,
)
from .model import REF_CALL, REF_TYPE, REF_VALUE, FileIndex

_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        _PARSER = make_parser(tree_sitter_python.language())
    return _PARSER


def _dotted(b: Builder, node: Node | None) -> str:
    return "".join(b.text(node).split())


def _docstring(b: Builder, body: Node | None) -> str:
    if body is None or not body.named_children:
        return ""
    first = body.named_children[0]
    if first.type != "expression_statement" or not first.named_children:
        return ""
    string = first.named_children[0]
    if string.type != "string":
        return ""
    for part in string.named_children:
        if part.type == "string_content":
            return dedent_first_line(b.text(part))
    return ""


def _with_decorators(node: Node) -> Node:
    parent = node.parent
    if parent is not None and parent.type == "decorated_definition":
        return parent
    return node


class _PythonHandler:
    def __init__(self, b: Builder) -> None:
        self.b = b

    def __call__(self, node: Node, scope: Scope) -> Pushed | None:
        kind = node.type
        if kind == "function_definition":
            return self.function(node, scope)
        if kind == "class_definition":
            return self.klass(node, scope)
        if kind == "call":
            return self.call(node, scope)
        if kind == "type":
            self.type_refs(node, scope)
            return []
        if kind == "import_statement":
            self.import_statement(node)
            return []
        if kind == "import_from_statement":
            self.import_from(node)
            return []
        return None

    # -- definitions ----------------------------------------------------------------

    def function(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        name = b.text(name_node)
        is_method = scope.kind == "class"
        range_node = _with_decorators(node)
        sym = b.add_symbol(
            node,
            name,
            "method" if is_method else "function",
            scope,
            range_node=range_node,
            signature=b.header(node, body),
            doc=_docstring(b, body),
            self_names=("self", "cls", "mcs"),
            cls=scope.cls,
        )
        inner = Scope(
            owner=sym.id,
            prefix=sym.qualname,
            kind="function",
            cls=scope.cls,
            self_names=("self", "cls", "mcs"),
        )
        return [(c, inner) for c in node.children if not same(c, name_node)]

    def klass(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        supers = node.child_by_field_name("superclasses")
        range_node = _with_decorators(node)
        bases: list[str] = []
        if supers is not None:
            for arg in supers.named_children:
                if arg.type in ("identifier", "attribute"):
                    bases.append(_dotted(b, arg))
        sym = b.add_symbol(
            node,
            b.text(name_node),
            "class",
            scope,
            range_node=range_node,
            signature=b.header(node, body),
            doc=_docstring(b, body),
            bases=bases,
        )
        for arg in supers.named_children if supers is not None else []:
            if arg.type == "identifier":
                b.add_ref(arg, sym.id, b.text(arg), REF_TYPE)
            elif arg.type == "attribute":
                self.attribute_ref(arg, sym.id, REF_TYPE)
        inner = Scope(owner=sym.id, prefix=sym.qualname, kind="class", cls=sym.qualname)
        pushed = [(body, inner)] if body is not None else []
        if supers is not None:
            for arg in supers.named_children:
                if arg.type == "keyword_argument":
                    pushed.append((arg, inner))
        return pushed

    # -- references -----------------------------------------------------------------

    def attribute_ref(self, node: Node, owner: str, kind: str) -> None:
        b = self.b
        attr = node.child_by_field_name("attribute")
        obj = node.child_by_field_name("object")
        receiver = UNKNOWN_RECEIVER
        if obj is not None and obj.type in ("identifier", "attribute"):
            receiver = simple_receiver(b.text(obj))
        if attr is not None:
            b.add_ref(attr, owner, b.text(attr), kind, receiver)

    def call(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if fn is not None:
            if fn.type == "identifier":
                b.add_ref(fn, scope.owner, b.text(fn), REF_CALL)
            elif fn.type == "attribute":
                self.attribute_ref(fn, scope.owner, REF_CALL)
        if args is not None:
            for arg in args.named_children:
                value = arg.child_by_field_name("value") if arg.type == "keyword_argument" else arg
                if value is None:
                    continue
                if value.type == "identifier":
                    b.add_ref(value, scope.owner, b.text(value), REF_VALUE)
                elif value.type == "attribute":
                    self.attribute_ref(value, scope.owner, REF_VALUE)
        pushed: list[tuple[Node, Scope]] = []
        for child in node.children:
            if same(child, fn) and fn.type in ("identifier", "attribute"):
                if fn.type == "attribute":
                    obj = fn.child_by_field_name("object")
                    if obj is not None:
                        pushed.append((obj, scope))
                continue
            pushed.append((child, scope))
        return pushed

    def type_refs(self, node: Node, scope: Scope) -> None:
        b = self.b
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur.type == "identifier":
                b.add_ref(cur, scope.owner, b.text(cur), REF_TYPE)
            elif cur.type == "attribute":
                self.attribute_ref(cur, scope.owner, REF_TYPE)
            else:
                stack.extend(cur.children)

    # -- imports --------------------------------------------------------------------

    def import_statement(self, node: Node) -> None:
        b = self.b
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                target = _dotted(b, child.child_by_field_name("name"))
                alias = b.text(child.child_by_field_name("alias"))
                b.add_import(alias, target)
            elif child.type == "dotted_name":
                dotted = _dotted(b, child)
                b.add_import(dotted, dotted)
                head = dotted.split(".")[0]
                if head != dotted:
                    b.add_import(head, head)

    def import_from(self, node: Node) -> None:
        b = self.b
        module = node.child_by_field_name("module_name")
        spec = _dotted(b, module)
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                name = _dotted(b, child.child_by_field_name("name"))
                alias = b.text(child.child_by_field_name("alias"))
                b.add_import(alias, spec, name)
            elif child.type == "dotted_name":
                name = _dotted(b, child)
                b.add_import(name, spec, name)


def extract(path: str, data: bytes) -> FileIndex:
    b = Builder(path, "python", data)
    tree = _parser().parse(data)
    b.index.has_error = tree.root_node.has_error
    walk(tree.root_node, Scope(owner=b.module_id), _PythonHandler(b))
    return b.finish()
