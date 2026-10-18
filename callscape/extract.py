"""Shared machinery for the tree-sitter based extractors.

Each language module provides a ``Handler`` that decides, node by node, whether a
syntax node is a definition, a reference, or just something to walk through. The
walk itself is iterative so very deep expression trees cannot blow the Python stack.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from tree_sitter import Language, Node, Parser

from .model import FileIndex, Import, Ref, Symbol


@dataclass(frozen=True)
class Scope:
    """Lexical context of a node: who owns refs found here, and how names are qualified."""

    owner: str  # id of the symbol that owns refs found in this scope
    prefix: str = ""  # qualname of the enclosing symbol ("" at module level)
    kind: str = "module"  # module | class | function | object
    cls: str | None = None  # qualname of the enclosing class, for self/this lookups
    self_names: tuple[str, ...] = ()


Pushed = Iterable[tuple[Node, Scope]]
NodeHandler = Callable[[Node, Scope], Pushed | None]


def make_parser(language_ptr: object) -> Parser:
    return Parser(Language(language_ptr))


class Builder:
    """Collects symbols, refs and imports for one file while a handler walks the tree."""

    def __init__(self, path: str, lang: str, data: bytes) -> None:
        self.path = path
        self.lang = lang
        self.data = data
        self._line_bytes = data.split(b"\n")
        self._line_starts: list[int] = []
        offset = 0
        for chunk in self._line_bytes:
            self._line_starts.append(offset)
            offset += len(chunk) + 1
        text = data.decode("utf-8", errors="replace")
        self.lines = [line.rstrip("\r") for line in text.split("\n")]
        self.index = FileIndex(path=path, lang=lang, lines=self.lines)
        self._ids: dict[str, int] = {}
        self.module_id = f"{path}::<module>"

    # -- text helpers ---------------------------------------------------------------

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    # Positions are derived from byte offsets: the Point objects returned by
    # ``Node.start_point`` are not safe to read attributes from on every Python build.

    def row_of(self, byte: int) -> int:
        """0-based line number of a byte offset."""
        return bisect_right(self._line_starts, byte) - 1

    def start_row(self, node: Node) -> int:
        return self.row_of(node.start_byte)

    def end_row(self, node: Node) -> int:
        return self.row_of(max(node.end_byte - 1, node.start_byte))

    def char_col(self, row: int, byte_col: int) -> int:
        """Convert a tree-sitter byte column into a character column."""
        if row >= len(self._line_bytes):
            return byte_col
        return len(self._line_bytes[row][:byte_col].decode("utf-8", errors="replace"))

    def header(self, node: Node, body: Node | None) -> str:
        """The source text of a definition up to its body, collapsed onto one line."""
        end = body.start_byte if body is not None else node.end_byte
        raw = self.data[node.start_byte : end].decode("utf-8", errors="replace")
        collapsed = " ".join(raw.split())
        return collapsed[:240]

    def finish(self) -> FileIndex:
        """Add the file-level pseudo symbol when top-level code makes calls, then sort."""
        if any(r.owner == self.module_id for r in self.index.refs):
            count = len(self.lines)
            while count > 1 and not self.lines[count - 1].strip():
                count -= 1
            self.index.symbols.append(
                Symbol(
                    id=self.module_id,
                    name="<module>",
                    qualname="<module>",
                    kind="module",
                    lang=self.lang,
                    path=self.path,
                    line=1,
                    end_line=count,
                    body_start=1,
                    signature=f"top-level code of {self.path}",
                )
            )
        self.index.symbols.sort(key=lambda s: (s.line, s.end_line))
        return self.index

    # -- recording ------------------------------------------------------------------

    def add_symbol(
        self,
        node: Node,
        name: str,
        kind: str,
        scope: Scope,
        *,
        range_node: Node | None = None,
        signature: str = "",
        doc: str = "",
        bases: list[str] | None = None,
        self_names: tuple[str, ...] = (),
        cls: str | None = None,
        is_default_export: bool = False,
        qualname: str | None = None,
    ) -> Symbol:
        span = range_node or node
        qual = qualname or (f"{scope.prefix}.{name}" if scope.prefix else name)
        sym_id = f"{self.path}::{qual}"
        if sym_id in self._ids:
            self._ids[sym_id] += 1
            sym_id = f"{sym_id}#{self.start_row(span) + 1}"
        else:
            self._ids[sym_id] = 1
        sym = Symbol(
            id=sym_id,
            name=name,
            qualname=qual,
            kind=kind,
            lang=self.lang,
            path=self.path,
            line=self.start_row(node) + 1,
            end_line=self.end_row(span) + 1,
            body_start=self.start_row(span) + 1,
            parent=scope.prefix or None,
            signature=signature,
            doc=doc,
            bases=bases or [],
            self_names=self_names,
            cls=cls,
            is_default_export=is_default_export,
        )
        self.index.symbols.append(sym)
        return sym

    def add_ref(
        self, node: Node, owner: str, name: str, kind: str, receiver: str | None = None
    ) -> None:
        if not name:
            return
        row = self.start_row(node)
        if self.end_row(node) != row:
            return
        col = self.char_col(row, node.start_byte - self._line_starts[row])
        end_col = self.char_col(row, node.end_byte - self._line_starts[row])
        self.index.refs.append(
            Ref(
                owner=owner,
                name=name,
                kind=kind,
                line=row + 1,
                col=col,
                end_col=end_col,
                receiver=receiver,
            )
        )

    def add_import(self, local: str, target: str, name: str | None = None) -> None:
        if local and target:
            self.index.imports.append(Import(local=local, target=target, name=name))


def walk(root: Node, scope: Scope, handler: NodeHandler) -> None:
    """Visit every node once, letting ``handler`` override how a node's children are walked."""
    stack: list[tuple[Node, Scope]] = [(root, scope)]
    while stack:
        node, sc = stack.pop()
        pushed = handler(node, sc)
        if pushed is None:
            for child in reversed(node.children):
                stack.append((child, sc))
        else:
            batch = list(pushed)
            for item in reversed(batch):
                stack.append(item)


UNKNOWN_RECEIVER = "?"


def same(a: Node | None, b: Node | None) -> bool:
    """Node identity. Tree-sitter hands out a fresh wrapper per access, so ``is`` never works."""
    return a is not None and b is not None and a.id == b.id


def simple_receiver(text: str) -> str:
    """Keep a receiver only if it is a plain dotted name; anything else becomes '?'."""
    compact = "".join(text.split())
    if not compact or any(ch in compact for ch in "()[]{}\"'`<>+-*/,;"):
        return UNKNOWN_RECEIVER
    return compact


def children_with(scope: Scope, nodes: Iterable[Node | None]) -> list[tuple[Node, Scope]]:
    return [(n, scope) for n in nodes if n is not None]


def descend(scope: Scope, **changes: object) -> Scope:
    return replace(scope, **changes)


def dedent_first_line(text: str, limit: int = 160) -> str:
    for line in text.strip().splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""
