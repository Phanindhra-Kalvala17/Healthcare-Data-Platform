import pandas as pd
import pytest

from config import settings
from processing.gold import cohort_summary, patient_features, pseudonymize


def test_pseudonym_is_stable_and_key_dependent():
    assert pseudonymize("P1", b"a" * 32) == pseudonymize("P1", b"a" * 32)
    assert pseudonymize("P1", b"a" * 32) != pseudonymize("P1", b"b" * 32)
    assert "P1" not in pseudonymize("P1", b"a" * 32)


def test_missing_or_short_key_is_refused(monkeypatch):
    monkeypatch.setenv("HDP_PSEUDONYMIZATION_KEY", "short")
    with pytest.raises(RuntimeError):
        settings.pseudonymization_key()


def test_features_drop_identifiers_and_cap_age():
    patients = pd.DataFrame({"patient_id": ["P1", "P2"], "sex": ["M", "F"], "first_name": ["A", "B"],
                             "birth_date": pd.to_datetime(["1920-01-01", "1980-06-15"])})
    encounters = pd.DataFrame({"patient_id": ["P1", "P1"], "encounter_id": ["E1", "E2"]})
    diagnoses = pd.DataFrame({"patient_id": ["P1"], "code": ["E11.9"]})
    t = pd.to_datetime(["2025-01-01", "2025-06-01", "2025-01-01"], utc=True)
    observations = pd.DataFrame({"patient_id": ["P1", "P1", "P2"], "name": ["bmi", "bmi", "glucose"],
                                 "value": [30.0, 32.0, 100.0], "effective_time": t})
    f = patient_features(patients, encounters, diagnoses, observations, b"k" * 32, as_of="2026-01-01")
    assert not {"patient_id", "first_name", "birth_date"} & set(f.columns)
    row = f.iloc[0]
    assert row["age"] == 90 and row["bmi_latest"] == 32.0 and row["encounter_count"] == 2 and row["has_diabetes"]
    assert f.iloc[1]["encounter_count"] == 0 and not f.iloc[1]["has_diabetes"]


def test_cohort_suppresses_small_cells():
    f = pd.DataFrame({"pseudo_id": [str(i) for i in range(12)], "age": [30] * 10 + [70] * 2,
                      "sex": ["F"] * 12, "has_diabetes": [True] * 3 + [False] * 9, "bmi_latest": [25.0] * 12})
    c = cohort_summary(f).set_index("age_band")
    assert c.loc["18-39", "patients"] == 10
    assert pd.isna(c.loc["18-39", "diabetes"])  # 3 cases < 5
    assert pd.isna(c.loc["60-74", "patients"]) and pd.isna(c.loc["60-74", "bmi_mean"])
