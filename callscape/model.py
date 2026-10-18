"""Plain data types shared by the extractors, the resolver and the renderer."""

from __future__ import annotations

from dataclasses import dataclass, field

# Symbol kinds that can be the target of a call or a plain reference.
CALLABLE_KINDS = frozenset({"function", "method", "class", "struct", "type", "interface"})
# Symbol kinds that can be the target of a type reference.
TYPE_KINDS = frozenset({"class", "struct", "interface", "type"})
# Kinds a bare (unqualified) name can resolve to. Methods are never reachable by a bare name.
BARE_KINDS = frozenset({"function", "class", "struct", "type", "interface"})

REF_CALL = "call"
REF_TYPE = "type"
REF_VALUE = "ref"


@dataclass
class Symbol:
    """A named definition: function, method, class, struct, interface, type or module."""

    id: str
    name: str
    qualname: str
    kind: str
    lang: str
    path: str
    line: int
    end_line: int
    body_start: int = 0
    parent: str | None = None
    signature: str = ""
    doc: str = ""
    bases: list[str] = field(default_factory=list)
    self_names: tuple[str, ...] = ()
    cls: str | None = None
    is_default_export: bool = False
    index: int = -1


@dataclass
class Ref:
    """A use of a name inside the body of ``owner``.

    ``receiver`` is the source text left of the final dot (``self`` in ``self.run()``),
    or None for a bare name. ``line`` is 1-based, columns are character offsets.
    """

    owner: str
    name: str
    kind: str
    line: int
    col: int
    end_col: int
    receiver: str | None = None
    targets: list[str] = field(default_factory=list)
    ambiguous: bool = False


@dataclass
class Import:
    """A name bound by an import statement.

    ``target`` is the module specifier exactly as written; ``name`` is the imported
    member (``None`` when the whole module is bound, ``"default"`` for a JS default import).
    """

    local: str
    target: str
    name: str | None = None


@dataclass
class FileIndex:
    path: str
    lang: str
    lines: list[str]
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    has_error: bool = False
    package: str = ""

    @property
    def directory(self) -> str:
        head, _, _ = self.path.rpartition("/")
        return head
