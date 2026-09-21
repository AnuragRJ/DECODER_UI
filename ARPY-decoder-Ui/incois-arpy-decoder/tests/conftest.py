"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

# conftest lives in argo-decoder-python/tests/
# the Coriolis repo is a sibling of argo-decoder-python under /home/user
THIS_FILE = Path(__file__).resolve()
ARGO_PY_ROOT = THIS_FILE.parents[1]  # .../argo-decoder-python
WORKSPACE = ARGO_PY_ROOT.parent  # .../home/user
DEMO_ROOT = WORKSPACE / "Coriolis-data-processing-chain-for-Argo-floats-container" / "decArgo_demo"


@pytest.fixture(scope="session")
def demo_root() -> Path:
    return DEMO_ROOT


@pytest.fixture(scope="session")
def demo_config(demo_root: Path) -> Path:
    return demo_root / "config" / "decoder_conf.json"


@pytest.fixture(scope="session")
def demo_input(demo_root: Path) -> Path:
    return demo_root / "input"
