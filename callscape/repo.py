"""Parse a whole repository into an indexed, resolved set of symbols."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import lang_go, lang_javascript, lang_python
from .model import FileIndex, Ref, Symbol
from .resolve import resolve_repo
from .scan import ScanError, scan

EXTRACTORS: dict[str, Callable[[str, bytes], FileIndex]] = {
    "python": lang_python.extract,
    "javascript": lang_javascript.extract,
    "go": lang_go.extract,
}


@dataclass
class Repo:
    root: Path
    files: dict[str, FileIndex] = field(default_factory=dict)
    symbols: list[Symbol] = field(default_factory=list)
    by_id: dict[str, Symbol] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def refs(self) -> Iterable[Ref]:
        for fi in self.files.values():
            yield from fi.refs

    def source_of(self, sym: Symbol, max_lines: int | None = None) -> tuple[list[str], bool]:
        """The lines of a symbol's definition, and whether they were truncated."""
        lines = self.files[sym.path].lines[sym.body_start - 1 : sym.end_line]
        if max_lines is not None and len(lines) > max_lines:
            return lines[:max_lines], True
        return lines, False


def _read_go_modules(root: Path, dirs: Iterable[str]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for d in dirs:
        try:
            text = (root / d / "go.mod").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "module":
                modules[parts[1].strip('"')] = d
                break
    return modules


def load_repo(
    path: str | Path,
    languages: Iterable[str] | None = None,
    exclude: Iterable[str] = (),
) -> Repo:
    """Scan, parse and resolve ``path``. Raises ScanError when there is nothing to analyse."""
    found = scan(path, languages, exclude)
    repo = Repo(root=found.root, skipped=list(found.skipped))
    for src in found.files:
        try:
            data = src.abspath.read_bytes()
        except OSError as exc:
            repo.skipped.append((src.path, f"unreadable: {exc.strerror or exc}"))
            continue
        if b"\x00" in data[:4096]:
            repo.skipped.append((src.path, "binary content"))
            continue
        repo.files[src.path] = EXTRACTORS[src.lang](src.path, data)
    if not repo.files:
        raise ScanError(f"no Python, JavaScript or Go source files found under {path}")
    resolve_repo(repo.files, _read_go_modules(repo.root, found.go_mod_dirs))
    for fi in repo.files.values():
        for sym in fi.symbols:
            sym.index = len(repo.symbols)
            repo.symbols.append(sym)
            repo.by_id[sym.id] = sym
    return repo
