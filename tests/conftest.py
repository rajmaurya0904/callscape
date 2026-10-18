from __future__ import annotations

from pathlib import Path

import pytest

from callscape.graph import Graph
from callscape.repo import Repo, load_repo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_path() -> Path:
    return FIXTURES / "sample"


@pytest.fixture(scope="session")
def repo(sample_path: Path) -> Repo:
    return load_repo(sample_path)


@pytest.fixture(scope="session")
def graph(repo: Repo) -> Graph:
    return Graph(repo)


def edge_targets(graph: Graph, caller_id: str) -> set[str]:
    """Ids of everything ``caller_id`` calls or references."""
    idx = graph.repo.by_id[caller_id].index
    return {s.id for s in graph.callees(idx)}
