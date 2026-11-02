import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def mock_costs(monkeypatch):
    """Tool tests use the mock cost files, whatever .env says. BigQuery tests set it themselves."""
    monkeypatch.setenv("COST_DATA_SOURCE", "mock")
