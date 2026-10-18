from __future__ import annotations

from pathlib import Path

import pytest

from callscape.scan import ScanError, parse_languages, scan


def write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def names(result) -> list[str]:
    return [f.path for f in result.files]


def test_finds_supported_extensions_only(tmp_path: Path) -> None:
    write(tmp_path, "a.py")
    write(tmp_path, "b.js")
    write(tmp_path, "c.go", "package c\n")
    write(tmp_path, "notes.txt")
    write(tmp_path, "d.mjs")
    assert names(scan(tmp_path)) == ["a.py", "b.js", "c.go", "d.mjs"]


def test_records_language_per_file(tmp_path: Path) -> None:
    write(tmp_path, "a.py")
    write(tmp_path, "b.jsx")
    langs = {f.path: f.lang for f in scan(tmp_path).files}
    assert langs == {"a.py": "python", "b.jsx": "javascript"}


def test_skips_vendored_and_hidden_directories(tmp_path: Path) -> None:
    write(tmp_path, "src/keep.py")
    write(tmp_path, "node_modules/lib/x.js")
    write(tmp_path, ".git/hooks/x.py")
    write(tmp_path, ".venv/lib/y.py")
    write(tmp_path, "__pycache__/z.py")
    write(tmp_path, "vendor/v.go")
    assert names(scan(tmp_path)) == ["src/keep.py"]


def test_language_filter(tmp_path: Path) -> None:
    write(tmp_path, "a.py")
    write(tmp_path, "b.js")
    assert names(scan(tmp_path, "js")) == ["b.js"]
    assert names(scan(tmp_path, ["python", "go"])) == ["a.py"]


def test_exclude_globs_match_paths_and_names(tmp_path: Path) -> None:
    write(tmp_path, "src/a.py")
    write(tmp_path, "tests/test_a.py")
    write(tmp_path, "src/gen_pb.py")
    result = scan(tmp_path, exclude=["tests", "*_pb.py"])
    assert names(result) == ["src/a.py"]


def test_minified_and_oversized_files_are_reported_not_parsed(tmp_path: Path) -> None:
    write(tmp_path, "app.min.js")
    write(tmp_path, "big.py", "x = 1\n" * 300_000)
    write(tmp_path, "ok.py")
    result = scan(tmp_path)
    assert names(result) == ["ok.py"]
    reasons = dict(result.skipped)
    assert reasons["app.min.js"] == "minified"
    assert "larger than" in reasons["big.py"]


def test_single_file_scan(tmp_path: Path) -> None:
    write(tmp_path, "solo.py")
    result = scan(tmp_path / "solo.py")
    assert names(result) == ["solo.py"]


def test_unsupported_single_file_is_an_error(tmp_path: Path) -> None:
    write(tmp_path, "readme.txt")
    with pytest.raises(ScanError):
        scan(tmp_path / "readme.txt")


def test_missing_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ScanError, match="does not exist"):
        scan(tmp_path / "nope")


def test_unknown_language_is_rejected() -> None:
    with pytest.raises(ScanError, match="unknown language"):
        parse_languages("python,cobol")


def test_language_aliases() -> None:
    assert parse_languages("py, JS ,golang") == frozenset({"python", "javascript", "go"})


def test_go_mod_directories_are_recorded(tmp_path: Path) -> None:
    write(tmp_path, "svc/go.mod", "module example.com/svc\n")
    write(tmp_path, "svc/main.go", "package main\n")
    assert scan(tmp_path).go_mod_dirs == ["svc"]
