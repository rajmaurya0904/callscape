"""Find the source files of a repository."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".go": "go",
}

LANGUAGE_ALIASES: dict[str, str] = {
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "js": "javascript",
    "go": "go",
    "golang": "go",
}

DEFAULT_SKIP_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        "env",
        "vendor",
        "dist",
        "build",
        "target",
        "site-packages",
        "bower_components",
    }
)

MAX_FILE_BYTES = 1_000_000


class ScanError(Exception):
    """Raised when the requested path cannot be scanned."""


@dataclass
class SourceFile:
    path: str  # posix path relative to the scan root
    abspath: Path
    lang: str


@dataclass
class ScanResult:
    root: Path
    files: list[SourceFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def parse_languages(spec: str | Iterable[str] | None) -> frozenset[str]:
    """Turn ``"py,go"`` (or a list) into canonical language names."""
    if spec is None:
        return frozenset(set(LANGUAGE_ALIASES.values()))
    parts = spec.split(",") if isinstance(spec, str) else list(spec)
    langs: set[str] = set()
    for part in parts:
        key = part.strip().lower()
        if not key:
            continue
        if key not in LANGUAGE_ALIASES:
            known = ", ".join(sorted(set(LANGUAGE_ALIASES.values())))
            raise ScanError(f"unknown language {part!r} (known: {known})")
        langs.add(LANGUAGE_ALIASES[key])
    if not langs:
        raise ScanError("no languages selected")
    return frozenset(langs)


def _is_excluded(rel: str, patterns: Iterable[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
            return True
        if fnmatch.fnmatch(rel + "/", pat.rstrip("/") + "/"):
            return True
    return False


def _walk(root: Path, exclude: tuple[str, ...]) -> Iterator[tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel_dir = base.relative_to(root).as_posix()
        keep = []
        for d in sorted(dirnames):
            if d.startswith(".") or d in DEFAULT_SKIP_DIRS or d.endswith(".egg-info"):
                continue
            rel = d if rel_dir == "." else f"{rel_dir}/{d}"
            if _is_excluded(rel, exclude):
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            yield rel, base / name


def scan(
    path: str | Path,
    languages: Iterable[str] | None = None,
    exclude: Iterable[str] = (),
) -> ScanResult:
    """Collect source files under ``path`` (a directory or a single file)."""
    root = Path(path)
    if not root.exists():
        raise ScanError(f"path does not exist: {path}")
    wanted = parse_languages(languages) if not isinstance(languages, frozenset) else languages
    patterns = tuple(exclude)
    result = ScanResult(root=root.resolve() if root.is_dir() else root.resolve().parent)

    if root.is_file():
        lang = LANGUAGE_EXTENSIONS.get(root.suffix.lower())
        if lang is None or lang not in wanted:
            raise ScanError(f"not a supported source file: {path}")
        result.files.append(SourceFile(root.name, root.resolve(), lang))
        return result

    for rel, abspath in _walk(root, patterns):
        lang = LANGUAGE_EXTENSIONS.get(abspath.suffix.lower())
        if lang is None or lang not in wanted:
            continue
        if rel.endswith((".min.js", ".bundle.js")):
            result.skipped.append((rel, "minified"))
            continue
        if _is_excluded(rel, patterns):
            continue
        try:
            size = abspath.stat().st_size
        except OSError as exc:
            result.skipped.append((rel, f"unreadable: {exc.strerror or exc}"))
            continue
        if size > MAX_FILE_BYTES:
            result.skipped.append((rel, f"larger than {MAX_FILE_BYTES // 1000} KB"))
            continue
        result.files.append(SourceFile(rel, abspath, lang))
    return result
