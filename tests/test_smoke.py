"""Smoke test: package imports cleanly. Replace/extend as modules land."""

import callscape


def test_version_is_set() -> None:
    assert callscape.__version__
