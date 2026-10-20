"""Integration tests: full landing -> Gold run on synthetic data, idempotency, retries and failure records."""
import json

import pandas as pd
import pytest

from healthcare_models.schemas import PII_COLUMNS
from ingestion import batch
from ingestion.sources import synthetic
from orchestration import pipeline


def test_end_to_end_run(tmp_path):
    record = pipeline.run(tmp_path, generate_patients=200)
    assert record["status"] == "succeeded"
    assert [s["step"] for s in record["steps"]] == ["generate", "bronze", "silver", "gold"]

    features = pd.read_parquet(tmp_path / "gold" / "patient_features.parquet")
    assert 0 < len(features) <= 200
    assert features["pseudo_id"].is_unique
    assert not set(PII_COLUMNS) & set(features.columns)

    quarantine = pd.read_parquet(tmp_path / "quarantine" / "observations.parquet")
    assert {"invalid_value", "implausible_value"} <= set(quarantine["_reject_reason"])
    silver_obs = pd.read_parquet(tmp_path / "silver" / "observations.parquet")
    assert silver_obs["observation_id"].is_unique
    assert (silver_obs.loc[silver_obs.code == "2345-7", "unit"] == "mg/dL").all()

    saved = json.loads((tmp_path / "runs" / f"{record['run_id']}.json").read_text())
    assert saved["status"] == "succeeded"


def test_reingesting_same_files_is_a_no_op(tmp_path):
    synthetic.generate(tmp_path / "landing", n_patients=20)
    first = batch.ingest(tmp_path / "landing", tmp_path)
    second = batch.ingest(tmp_path / "landing", tmp_path)
    assert first["patients"] > 0
    assert second == {"patients": 0, "encounters": 0, "observations": 0}
    assert len(batch.read_bronze(tmp_path, "patients")) == first["patients"]


def test_new_batch_is_ingested_incrementally(tmp_path):
    synthetic.generate(tmp_path / "landing", n_patients=20, seed=1)
    batch.ingest(tmp_path / "landing", tmp_path)
    synthetic.generate(tmp_path / "landing", n_patients=20, seed=2)
    second = batch.ingest(tmp_path / "landing", tmp_path)
    assert second["patients"] > 0
    assert set(batch.read_bronze(tmp_path, "patients")["_source_file"].str[:11]) == {"batch_seed1", "batch_seed2"}


def test_retry_recovers_from_transient_io_error(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("file locked")
        return "ok"

    assert pipeline.with_retry("x", flaky) == "ok"
    assert len(calls) == 3


def test_failed_run_is_recorded_and_alerted(tmp_path, monkeypatch):
    monkeypatch.setenv("HDP_PSEUDONYMIZATION_KEY", "")
    with pytest.raises(RuntimeError):
        pipeline.run(tmp_path, generate_patients=20)
    (run_file,) = (tmp_path / "runs").glob("*.json")
    record = json.loads(run_file.read_text())
    assert record["status"] == "failed"
    assert record["steps"][-1] == {**record["steps"][-1], "step": "gold", "status": "failed"}
    assert "pipeline run failed" in (tmp_path / "alerts.jsonl").read_text()


def test_quality_breach_raises_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.settings, "QUALITY_THRESHOLD", 0.999)
    record = pipeline.run(tmp_path, generate_patients=50)
    assert record["status"] == "succeeded_with_quality_alerts"
    assert "data quality below threshold" in (tmp_path / "alerts.jsonl").read_text()
