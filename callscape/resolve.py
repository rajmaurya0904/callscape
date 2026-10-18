"""Resolve the raw names found by the extractors to symbols defined in the repository.

Resolution is purely name based (there is no type inference). A reference is looked up
through, in order: the lexical scope, the file's imports, the package or module it
belongs to, and finally a conservative repo-wide fallback. A name that is clearly bound
to something outside the repository (``os.getcwd``) is left unresolved on purpose.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict

from .model import (
    BARE_KINDS,
    CALLABLE_KINDS,
    REF_CALL,
    REF_TYPE,
    REF_VALUE,
    TYPE_KINDS,
    FileIndex,
    Import,
    Ref,
    Symbol,
)

MAX_AMBIGUOUS = 4
JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx")
CONSTRUCTORS = {"python": "__init__", "javascript": "constructor"}

# Method names so common on built-in containers and strings that a repo-wide match on
# them says almost nothing. They only resolve when the same file defines them.
COMMON_METHOD_NAMES = frozenset(
    """get set add append update pop keys values items join split strip format read write
    close open remove clear copy extend insert index count sort lower upper replace find
    startswith endswith encode decode push map filter forEach then catch toString""".split()
)

Binding = tuple[str, "str | Symbol | None"]


class Resolver:
    def __init__(
        self, files: dict[str, FileIndex], go_modules: dict[str, str] | None = None
    ) -> None:
        self.files = files
        self.by_id: dict[str, Symbol] = {}
        self.by_qual: dict[tuple[str, str], Symbol] = {}
        self.top: dict[str, dict[str, Symbol]] = defaultdict(dict)
        self.callables_by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.methods_by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.imports: dict[str, dict[str, Import]] = {}
        self.py_modules: dict[str, list[str]] = defaultdict(list)
        self.go_dirs: set[str] = set()
        self.go_modules = go_modules or {}  # module path -> directory relative to the root
        self._binding_cache: dict[tuple[str, str], Binding | None] = {}
        self._index()

    # -- indexing -------------------------------------------------------------------

    @staticmethod
    def scope_key(fi: FileIndex) -> str:
        """Names are visible across the files of a Go package, but only within a file elsewhere."""
        return fi.directory if fi.lang == "go" else fi.path

    def _index(self) -> None:
        for fi in self.files.values():
            key = self.scope_key(fi)
            self.imports[fi.path] = {imp.local: imp for imp in fi.imports}
            if fi.lang == "go":
                self.go_dirs.add(fi.directory)
            if fi.lang == "python":
                parts = fi.path[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for i in range(len(parts)):
                    self.py_modules[".".join(parts[i:])].append(fi.path)
            for sym in fi.symbols:
                self.by_id[sym.id] = sym
                if sym.kind == "module":
                    continue
                self.by_qual.setdefault((key, sym.qualname), sym)
                if sym.parent is None and sym.kind != "method":
                    self.top[key].setdefault(sym.name, sym)
                if sym.kind == "method":
                    self.methods_by_name[sym.name].append(sym)
                if sym.kind in BARE_KINDS:
                    self.callables_by_name[sym.name].append(sym)

    # -- module and import resolution -----------------------------------------------

    def _py_module(self, spec: str, fi: FileIndex) -> str | None:
        if spec.startswith("."):
            dots = len(spec) - len(spec.lstrip("."))
            rest = spec[dots:]
            base = fi.directory
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            rel = posixpath.join(base, rest.replace(".", "/")) if rest else base
            rel = posixpath.normpath(rel) if rel else ""
            for cand in (f"{rel}.py" if rest else "", posixpath.join(rel, "__init__.py")):
                cand = cand.lstrip("/")
                if cand and cand in self.files:
                    return cand
            return None
        paths = self.py_modules.get(spec)
        if not paths:
            return None
        return max(paths, key=lambda p: (_common_prefix(p, fi.path), -len(p)))

    def _js_module(self, spec: str, fi: FileIndex) -> str | None:
        if not spec.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(fi.directory, spec))
        if base in self.files:
            return base
        for ext in JS_EXTENSIONS:
            if base + ext in self.files:
                return base + ext
        for ext in JS_EXTENSIONS:
            cand = posixpath.join(base, "index" + ext)
            if cand in self.files:
                return cand
        return None

    def _go_package(self, spec: str) -> str | None:
        for module, moddir in sorted(self.go_modules.items(), key=lambda kv: -len(kv[0])):
            if spec == module or spec.startswith(module + "/"):
                rel = posixpath.join(moddir, spec[len(module) :].lstrip("/")).strip("/")
                rel = posixpath.normpath(rel) if rel else ""
                if rel in self.go_dirs:
                    return rel
        parts = spec.split("/")
        for k in range(len(parts) - 1):
            suffix = "/".join(parts[k:])
            matches = [d for d in self.go_dirs if d == suffix or d.endswith("/" + suffix)]
            if len(matches) == 1:
                return matches[0]
        return None

    def binding(self, local: str, fi: FileIndex, depth: int = 0) -> Binding | None:
        """What an imported local name refers to: a scope, a symbol, or 'external'."""
        imp = self.imports.get(fi.path, {}).get(local)
        if imp is None:
            return None
        cache_key = (fi.path, local)
        if cache_key in self._binding_cache:
            return self._binding_cache[cache_key]
        result = self._compute_binding(imp, fi, depth)
        self._binding_cache[cache_key] = result
        return result

    def _compute_binding(self, imp: Import, fi: FileIndex, depth: int) -> Binding:
        external: Binding = ("external", None)
        if fi.lang == "go":
            pkg = self._go_package(imp.target)
            return ("scope", pkg) if pkg is not None else external
        if fi.lang == "javascript":
            target = self._js_module(imp.target, fi)
            if target is None:
                return external
            if imp.name is None:
                return ("scope", target)
            tfi = self.files[target]
            if imp.name == "default":
                for sym in tfi.symbols:
                    if sym.is_default_export:
                        return ("symbol", sym)
                sym = self.top[target].get(imp.local)
                return ("symbol", sym) if sym else ("scope", target)
            sym = self.top[target].get(imp.name)
            if sym is not None:
                return ("symbol", sym)
            return self._follow_reexport(imp.name, tfi, depth) or external
        # python
        module = self._py_module(imp.target, fi)
        if imp.name is None:
            return ("scope", module) if module else external
        if module is not None:
            sym = self.top[module].get(imp.name)
            if sym is not None:
                return ("symbol", sym)
            followed = self._follow_reexport(imp.name, self.files[module], depth)
            if followed is not None:
                return followed
        sub_spec = imp.target + imp.name if imp.target.endswith(".") else f"{imp.target}.{imp.name}"
        sub = self._py_module(sub_spec, fi)
        return ("scope", sub) if sub else external

    def _follow_reexport(self, name: str, fi: FileIndex, depth: int) -> Binding | None:
        if depth >= 3 or name not in self.imports.get(fi.path, {}):
            return None
        result = self.binding(name, fi, depth + 1)
        return result if result and result[0] != "external" else None

    # -- lookups --------------------------------------------------------------------

    def _bases_of(self, cls: Symbol) -> list[Symbol]:
        fi = self.files[cls.path]
        found: list[Symbol] = []
        for base in cls.bases:
            head, _, tail = base.rpartition(".")
            probe = Ref(
                owner=cls.id,
                name=tail or base,
                kind=REF_TYPE,
                line=0,
                col=0,
                end_col=0,
                receiver=head or None,
            )
            targets, _ = self._resolve(probe, fi, self.by_id[cls.id])
            found.extend(t for t in targets if t.kind in TYPE_KINDS and t is not cls)
        return found

    def methods_of(
        self, cls: Symbol, name: str, seen: set[str] | None = None, skip_self: bool = False
    ) -> list[Symbol]:
        seen = seen if seen is not None else set()
        if cls.id in seen or len(seen) > 12:
            return []
        seen.add(cls.id)
        fi = self.files[cls.path]
        if not skip_self:
            hit = self.by_qual.get((self.scope_key(fi), f"{cls.qualname}.{name}"))
            if hit is not None and hit.kind == "method":
                return [hit]
        for base in self._bases_of(cls):
            hits = self.methods_of(base, name, seen)
            if hits:
                return hits
        return []

    def _class_for(self, qualname: str, fi: FileIndex) -> Symbol | None:
        sym = self.by_qual.get((self.scope_key(fi), qualname))
        return sym if sym is not None and sym.kind in TYPE_KINDS else None

    def _lexical(
        self, name: str, fi: FileIndex, owner: Symbol | None, kinds: frozenset[str]
    ) -> Symbol | None:
        key = self.scope_key(fi)
        qual = owner.qualname if owner is not None and owner.kind != "module" else ""
        first = True
        while True:
            if qual:
                scope_sym = self.by_qual.get((key, qual))
                skip = (not first and scope_sym is not None and scope_sym.kind in TYPE_KINDS) or (
                    fi.lang == "go" and "." in qual
                )
            else:
                skip = False
            if not skip:
                cand = self.by_qual.get((key, f"{qual}.{name}" if qual else name))
                if cand is not None and cand.kind in kinds:
                    return cand
            first = False
            if not qual:
                return None
            qual = qual.rpartition(".")[0]

    # -- resolution -----------------------------------------------------------------

    def resolve_all(self) -> None:
        for fi in self.files.values():
            for ref in fi.refs:
                owner = self.by_id.get(ref.owner)
                targets, ambiguous = self._resolve(ref, fi, owner)
                seen: dict[str, None] = {}
                for t in targets:
                    seen.setdefault(t.id, None)
                ref.targets = list(seen)
                ref.ambiguous = ambiguous or len(ref.targets) > 1

    def _kinds(self, ref: Ref) -> frozenset[str]:
        return TYPE_KINDS if ref.kind == REF_TYPE else BARE_KINDS

    def _resolve(self, ref: Ref, fi: FileIndex, owner: Symbol | None) -> tuple[list[Symbol], bool]:
        targets = (
            self._resolve_bare(ref, fi, owner)
            if ref.receiver is None
            else self._resolve_member(ref, fi, owner)
        )
        if ref.kind == REF_CALL and fi.lang in CONSTRUCTORS:
            extra: list[Symbol] = []
            ctor = CONSTRUCTORS[fi.lang]
            for t in targets:
                if t.kind == "class":
                    extra.extend(self.methods_of(t, ctor))
            targets = targets + extra
        return targets, False

    def _resolve_bare(self, ref: Ref, fi: FileIndex, owner: Symbol | None) -> list[Symbol]:
        name, kinds = ref.name, self._kinds(ref)
        hit = self._lexical(name, fi, owner, kinds)
        if hit is not None:
            return [hit]
        bound = self.binding(name, fi)
        if bound is not None:
            if bound[0] == "symbol":
                sym = bound[1]
                assert isinstance(sym, Symbol)
                return [sym] if sym.kind in kinds else []
            return []
        if ref.kind == REF_VALUE:
            return []
        if fi.lang == "go":
            return []
        cands = [
            s
            for s in self.callables_by_name.get(name, ())
            if s.lang == fi.lang and s.kind in kinds and s.parent is None
        ]
        if len(cands) == 1:
            return cands
        near = [s for s in cands if posixpath.dirname(s.path) == fi.directory]
        return near if 0 < len(near) <= MAX_AMBIGUOUS else []

    def _resolve_member(self, ref: Ref, fi: FileIndex, owner: Symbol | None) -> list[Symbol]:
        name, recv = ref.name, ref.receiver or ""
        kinds = self._kinds(ref)
        # self / this / the Go receiver variable / super
        scope_sym = owner
        if (
            scope_sym is not None
            and scope_sym.cls
            and (recv in scope_sym.self_names or recv == "super")
        ):
            cls = self._class_for(scope_sym.cls, fi)
            if cls is not None:
                hits = self.methods_of(cls, name, skip_self=recv == "super")
                if hits:
                    return hits
                if recv == "super":
                    return []
            return self._unknown_receiver(ref, fi)
        head, _, rest = recv.partition(".")
        exact = self.binding(recv, fi)
        if exact is not None:
            return self._from_binding(exact, name, kinds)
        if rest:
            bound = self.binding(head, fi)
            if bound is not None:
                return self._submodule_member(head, rest, name, kinds, fi, bound)
        else:
            cls_hit = self._lexical(recv, fi, owner, TYPE_KINDS)
            if cls_hit is not None:
                return self.methods_of(cls_hit, name)
        return self._unknown_receiver(ref, fi)

    def _submodule_member(
        self, head: str, rest: str, name: str, kinds: frozenset[str], fi: FileIndex, bound: Binding
    ) -> list[Symbol]:
        """``pkg.sub.func()`` where ``pkg`` is an imported Python package."""
        if bound[0] != "scope" or fi.lang != "python":
            return []
        imp = self.imports[fi.path][head]
        module = self._py_module(f"{imp.target}.{rest}", fi)
        if module is None:
            return []
        hit = self.top.get(module, {}).get(name)
        return [hit] if hit is not None and hit.kind in kinds else []

    def _from_binding(self, bound: Binding, name: str, kinds: frozenset[str]) -> list[Symbol]:
        kind, value = bound
        if kind == "symbol":
            sym = value
            assert isinstance(sym, Symbol)
            if sym.kind in TYPE_KINDS:
                return self.methods_of(sym, name)
            return []
        if kind == "scope" and isinstance(value, str):
            hit = self.top.get(value, {}).get(name)
            return [hit] if hit is not None and hit.kind in kinds else []
        return []

    def _unknown_receiver(self, ref: Ref, fi: FileIndex) -> list[Symbol]:
        if ref.kind != REF_CALL:
            return []
        cands = [s for s in self.methods_by_name.get(ref.name, ()) if s.lang == fi.lang]
        key = self.scope_key(fi)
        local = [s for s in cands if self.scope_key(self.files[s.path]) == key]
        if local:
            return local[:MAX_AMBIGUOUS]
        if ref.name in COMMON_METHOD_NAMES:
            return []
        return cands if 0 < len(cands) <= MAX_AMBIGUOUS else []


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.split("/"), b.split("/"), strict=False):
        if x != y:
            break
        n += 1
    return n


def resolve_repo(files: dict[str, FileIndex], go_modules: dict[str, str] | None = None) -> Resolver:
    resolver = Resolver(files, go_modules)
    resolver.resolve_all()
    return resolver


__all__ = ["CALLABLE_KINDS", "Resolver", "resolve_repo"]
