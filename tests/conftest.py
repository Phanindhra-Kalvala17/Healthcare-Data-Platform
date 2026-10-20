import pandas as pd
import pytest

TEST_KEY = "k" * 40


@pytest.fixture(autouse=True)
def pseudonymization_key(monkeypatch):
    monkeypatch.setenv("HDP_PSEUDONYMIZATION_KEY", TEST_KEY)


def bronze(rows: list[dict], ingested_at="2026-01-01") -> pd.DataFrame:
    """Build a Bronze-shaped frame: raw string values plus lineage columns."""
    return pd.DataFrame(rows).assign(_ingested_at=pd.Timestamp(ingested_at, tz="UTC"), _source_system="test")
