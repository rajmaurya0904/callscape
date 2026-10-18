"""Packaging checks: the version, the console script and the bundled viewer assets."""

from __future__ import annotations

from importlib import resources

import callscape


def test_version_is_set() -> None:
    assert callscape.__version__


def test_viewer_assets_are_packaged() -> None:
    assets = resources.files("callscape").joinpath("assets")
    for name in ("viewer.html", "viewer.css", "viewer.js"):
        assert assets.joinpath(name).read_text(encoding="utf-8").strip()


def test_viewer_template_has_every_marker() -> None:
    html = resources.files("callscape").joinpath("assets", "viewer.html").read_text("utf-8")
    for marker in ("__TITLE__", "/*__CSS__*/", "/*__JS__*/", "__DATA__"):
        assert html.count(marker) == 1
