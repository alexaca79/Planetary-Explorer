"""Pytest configuration for pipeline unit tests.

Adds container-app/ to sys.path so `from pipeline import ...` works when
running `pytest tests/` from the container-app directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_CONTAINER_APP = _HERE.parent
if str(_CONTAINER_APP) not in sys.path:
    sys.path.insert(0, str(_CONTAINER_APP))


@pytest.fixture(
    params=[
        pytest.param(location, id=f"{location['code']}-{location['name']}")
        for location in json.loads(
            (_HERE / "fixtures" / "canadian_locations.json").read_text(encoding="utf-8")
        )
    ]
)
def canadian_location(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Provide representative points across all provinces, territories, and remote limits."""
    return dict(request.param)
