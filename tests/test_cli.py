from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from callscape import __version__
from callscape.cli import main


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_a_usage_error(capsys) -> None:
    assert main([]) == 2
    assert "required" in capsys.readouterr().err


def test_build_writes_the_html_file(capsys, sample_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    code, stdout, _ = run(capsys, "build", sample_path, "-o", out)
    assert code == 0
    assert out.exists()
    assert "9 files" in stdout
    assert "wrote" in stdout
    assert "callscape-data" in out.read_text(encoding="utf-8")


def test_build_language_filter(capsys, sample_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "go.html"
    code, stdout, _ = run(capsys, "build", sample_path, "--lang", "go", "-o", out)
    assert code == 0
    assert "2 files" in stdout


def test_build_exclude(capsys, sample_path: Path, tmp_path: Path) -> None:
    code, stdout, _ = run(
        capsys,
        "build",
        sample_path,
        "--exclude",
        "web",
        "--exclude",
        "goapp",
        "-o",
        tmp_path / "a.html",
    )
    assert code == 0
    assert "4 files" in stdout


def test_build_on_missing_path_fails_cleanly(capsys, tmp_path: Path) -> None:
    code, _, err = run(capsys, "build", tmp_path / "nope", "-o", tmp_path / "x.html")
    assert code == 1
    assert "does not exist" in err
    assert not (tmp_path / "x.html").exists()


def test_build_on_directory_without_sources(capsys, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "notes.txt").write_text("hi", encoding="utf-8")
    code, _, err = run(capsys, "build", tmp_path / "empty", "-o", tmp_path / "x.html")
    assert code == 1
    assert "no Python, JavaScript or Go source files" in err


def test_unknown_language_is_reported(capsys, sample_path: Path, tmp_path: Path) -> None:
    code, _, err = run(capsys, "build", sample_path, "--lang", "cobol", "-o", tmp_path / "x.html")
    assert code == 1
    assert "unknown language" in err


def test_unwritable_output_is_reported(capsys, sample_path: Path, tmp_path: Path) -> None:
    code, _, err = run(capsys, "build", sample_path, "-o", tmp_path / "no" / "dir" / "x.html")
    assert code == 1
    assert "cannot write" in err


def test_build_rejects_nonsense_body_limit(capsys, sample_path: Path, tmp_path: Path) -> None:
    code, _, err = run(
        capsys, "build", sample_path, "--max-body-lines", "0", "-o", tmp_path / "x.html"
    )
    assert code == 2
    assert "at least 1" in err


def test_syntax_errors_produce_a_warning(capsys, tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    code, _, err = run(capsys, "build", tmp_path, "-o", tmp_path / "o.html")
    assert code == 0
    assert "syntax errors in bad.py" in err


def test_stats_output(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "stats", sample_path)
    assert code == 0
    assert "files      9 (2 go, 3 javascript, 4 python)" in out
    assert "most called" in out
    assert "call cycles: 2" in out


def test_stats_json(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "stats", sample_path, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["files"] == 9
    assert data["call_sites_resolved"] > 0


def test_callees_tree(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "callees", sample_path, "main.py::main", "--depth", "2")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("main  (main.py:")
    assert any("Engine.run" in line for line in lines)
    assert any(line.startswith("    ") or "|   " in line for line in lines)


def test_callers_tree(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "callers", sample_path, "pkg/helpers.py::fmt")
    assert code == 0
    assert "Engine.step" in out
    assert "log" in out


def test_callers_with_no_result_exits_1(capsys, sample_path: Path) -> None:
    code, out, err = run(capsys, "callers", sample_path, "goapp/main.go::main")
    assert code == 1
    assert "is not called" in err


def test_ambiguous_symbol_exits_2_and_lists_candidates(capsys, sample_path: Path) -> None:
    code, _, err = run(capsys, "callers", sample_path, "fmt")
    assert code == 2
    assert "pkg/helpers.py::fmt" in err
    assert "web/util.js::fmt" in err


def test_unknown_symbol_exits_1(capsys, sample_path: Path) -> None:
    code, _, err = run(capsys, "callees", sample_path, "nothing_here")
    assert code == 1
    assert "no symbol matches" in err


def test_cycles_are_marked_in_trees(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "callees", sample_path, "is_even", "--depth", "4")
    assert code == 0
    assert "(cycle)" in out


def test_path_command(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "path", sample_path, "main.py::main", "pkg/helpers.py::fmt")
    assert code == 0
    assert out.splitlines()[-1] == "3 call(s)"
    assert "Engine.step" in out


def test_path_command_without_a_path_exits_1(capsys, sample_path: Path) -> None:
    code, _, err = run(capsys, "path", sample_path, "main.py::main", "web/app.js::boot")
    assert code == 1
    assert "no call path" in err


def test_dot_output(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "dot", sample_path)
    assert code == 0
    assert out.startswith("digraph callscape {")
    assert 'label="Engine.run"' in out
    assert "->" in out
    assert out.rstrip().endswith("}")


def test_dot_focus_limits_the_graph(capsys, sample_path: Path) -> None:
    code, out, _ = run(capsys, "dot", sample_path, "--focus", "Engine.run", "--depth", "1")
    assert code == 0
    assert 'label="Engine.run"' in out
    assert 'label="Server.Run"' not in out
    assert "fillcolor=lightyellow" in out


def test_json_export_to_file(capsys, sample_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "g.json"
    code, _, err = run(capsys, "json", sample_path, "-o", out)
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert "pkg/core.py::Engine.run" in node_ids
    for edge in data["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids
        assert edge["kind"] in {"call", "ref", "type"}
    assert data["stats"]["files"] == 9


def test_module_entry_point_runs_in_a_subprocess(sample_path: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "callscape", "stats", str(sample_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "symbols" in result.stdout
