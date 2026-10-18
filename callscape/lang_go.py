"""Go extractor: functions, methods, structs, interfaces, calls and imports."""

from __future__ import annotations

import tree_sitter_go
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

GO_BUILTIN_TYPES = frozenset(
    {
        "bool", "byte", "complex64", "complex128", "error", "float32", "float64", "int",
        "int8", "int16", "int32", "int64", "rune", "string", "uint", "uint8", "uint16",
        "uint32", "uint64", "uintptr", "any", "comparable",
    }
)  # fmt: skip

GO_BUILTIN_FUNCS = frozenset(
    {
        "append", "cap", "clear", "close", "complex", "copy", "delete", "imag", "len",
        "make", "max", "min", "new", "panic", "print", "println", "real", "recover",
    }
)  # fmt: skip


def _parser():
    global _PARSER
    if _PARSER is None:
        _PARSER = make_parser(tree_sitter_go.language())
    return _PARSER


def _base_type(b: Builder, node: Node | None) -> tuple[str, str | None, Node | None]:
    """Strip pointers/generics off a type node: returns (name, package, name node)."""
    while node is not None:
        if node.type == "type_identifier":
            return b.text(node), None, node
        if node.type == "qualified_type":
            name_node = node.child_by_field_name("name")
            return b.text(name_node), b.text(node.child_by_field_name("package")), name_node
        if node.type in ("pointer_type", "parenthesized_type"):
            node = next(iter(node.named_children), None)
        elif node.type == "generic_type":
            node = node.child_by_field_name("type")
        else:
            break
    return "", None, None


class _GoHandler:
    def __init__(self, b: Builder) -> None:
        self.b = b

    def __call__(self, node: Node, scope: Scope) -> Pushed | None:
        kind = node.type
        if kind == "package_clause":
            ident = next((c for c in node.named_children if c.type == "package_identifier"), None)
            self.b.index.package = self.b.text(ident)
            return []
        if kind == "import_spec":
            self.import_spec(node)
            return []
        if kind == "function_declaration":
            return self.function(node, scope)
        if kind == "method_declaration":
            return self.method(node, scope)
        if kind in ("type_spec", "type_alias"):
            return self.type_spec(node, scope)
        if kind == "call_expression":
            return self.call(node, scope)
        if kind == "qualified_type":
            name, pkg, name_node = _base_type(self.b, node)
            if name_node is not None:
                self.b.add_ref(name_node, scope.owner, name, REF_TYPE, pkg)
            return []
        if kind == "type_identifier":
            name = self.b.text(node)
            if name not in GO_BUILTIN_TYPES:
                self.b.add_ref(node, scope.owner, name, REF_TYPE)
            return []
        return None

    # -- definitions ----------------------------------------------------------------

    def function(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        sym = b.add_symbol(
            node, b.text(name_node), "function", scope, signature=b.header(node, body)
        )
        inner = Scope(owner=sym.id, prefix=sym.qualname, kind="function")
        return [(c, inner) for c in node.children if not same(c, name_node)]

    def method(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        receiver = node.child_by_field_name("receiver")
        recv_type, recv_name = "", ""
        if receiver is not None:
            decl = next((c for c in receiver.named_children), None)
            if decl is not None:
                recv_type, _, _ = _base_type(b, decl.child_by_field_name("type"))
                recv_name = b.text(decl.child_by_field_name("name"))
        name = b.text(name_node)
        qual = f"{recv_type}.{name}" if recv_type else name
        sym = b.add_symbol(
            node,
            name,
            "method",
            scope,
            signature=b.header(node, body),
            self_names=(recv_name,) if recv_name and recv_name != "_" else (),
            cls=recv_type or None,
            qualname=qual,
        )
        sym.parent = recv_type or None
        inner = Scope(
            owner=sym.id,
            prefix=sym.qualname,
            kind="function",
            cls=recv_type or None,
            self_names=sym.self_names,
        )
        skip = (name_node, receiver)
        return [(c, inner) for c in node.children if not any(same(c, s) for s in skip)]

    def type_spec(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        name_node = node.child_by_field_name("name")
        type_node = node.child_by_field_name("type")
        decl = node.parent
        range_node = node
        if decl is not None and decl.type == "type_declaration":
            specs = [c for c in decl.named_children if c.type in ("type_spec", "type_alias")]
            if len(specs) == 1:
                range_node = decl
        kind = "type"
        bases: list[str] = []
        if type_node is not None and type_node.type == "struct_type":
            kind = "struct"
            field_list = next(
                (c for c in type_node.named_children if c.type == "field_declaration_list"), None
            )
            for fld in field_list.named_children if field_list is not None else []:
                if fld.type == "field_declaration" and fld.child_by_field_name("name") is None:
                    base, pkg, _ = _base_type(b, fld.child_by_field_name("type"))
                    if base:
                        bases.append(f"{pkg}.{base}" if pkg else base)
        elif type_node is not None and type_node.type == "interface_type":
            kind = "interface"
        name = b.text(name_node)
        word = {"struct": "struct", "interface": "interface"}.get(kind, "")
        sym = b.add_symbol(
            node,
            name,
            kind,
            scope,
            range_node=range_node,
            signature=f"type {name} {word}".strip()
            if word
            else b.header(range_node, None).split("\n")[0],
            bases=bases,
        )
        inner = Scope(owner=sym.id, prefix=sym.qualname, kind="type", cls=sym.qualname)
        return [(c, inner) for c in node.children if not same(c, name_node)]

    # -- references -----------------------------------------------------------------

    def selector_ref(self, node: Node, owner: str, kind: str) -> None:
        b = self.b
        operand = node.child_by_field_name("operand")
        field = node.child_by_field_name("field")
        receiver = UNKNOWN_RECEIVER
        if operand is not None and operand.type in ("identifier", "selector_expression"):
            receiver = simple_receiver(b.text(operand))
        if field is not None:
            b.add_ref(field, owner, b.text(field), kind, receiver)

    def call(self, node: Node, scope: Scope) -> Pushed:
        b = self.b
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        skip: Node | None = None
        if fn is not None:
            if fn.type == "identifier":
                name = b.text(fn)
                if name not in GO_BUILTIN_FUNCS:
                    b.add_ref(fn, scope.owner, name, REF_CALL)
                skip = fn
            elif fn.type == "selector_expression":
                self.selector_ref(fn, scope.owner, REF_CALL)
                skip = fn
        if args is not None:
            for arg in args.named_children:
                if arg.type == "identifier":
                    b.add_ref(arg, scope.owner, b.text(arg), REF_VALUE)
                elif arg.type == "selector_expression":
                    self.selector_ref(arg, scope.owner, REF_VALUE)
        pushed: list[tuple[Node, Scope]] = []
        for child in node.children:
            if same(child, skip):
                if child.type == "selector_expression":
                    operand = child.child_by_field_name("operand")
                    if operand is not None and operand.type not in ("identifier",):
                        pushed.append((operand, scope))
                continue
            pushed.append((child, scope))
        return pushed

    # -- imports --------------------------------------------------------------------

    def import_spec(self, node: Node) -> None:
        b = self.b
        path_node = node.child_by_field_name("path")
        spec = "".join(
            b.text(c) for c in (path_node.named_children if path_node is not None else [])
        )
        if not spec:
            return
        alias = node.child_by_field_name("name")
        local = b.text(alias) if alias is not None else spec.rsplit("/", 1)[-1]
        if local in ("_", "."):
            return
        b.add_import(local, spec)


def extract(path: str, data: bytes) -> FileIndex:
    b = Builder(path, "go", data)
    tree = _parser().parse(data)
    b.index.has_error = tree.root_node.has_error
    walk(tree.root_node, Scope(owner=b.module_id), _GoHandler(b))
    return b.finish()
