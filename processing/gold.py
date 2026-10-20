"""Gold: pseudonymized patient-level features and small-cell-suppressed cohort aggregates."""
import hashlib
import hmac
import logging
from pathlib import Path

import pandas as pd

from config.settings import MIN_CELL_SIZE
from healthcare_models.schemas import DIABETES_ICD10_PREFIX, PII_COLUMNS
from ingestion.batch import write_parquet

log = logging.getLogger(__name__)


def pseudonymize(patient_id: str, key: bytes) -> str:
    """Keyed hash: stable across runs for linkage, not reversible without the key."""
    return hmac.new(key, patient_id.encode(), hashlib.sha256).hexdigest()[:24]


def patient_features(patients, encounters, diagnoses, observations, key: bytes, as_of=None) -> pd.DataFrame:
    as_of = pd.Timestamp(as_of) if as_of else pd.Timestamp.now().normalize()
    f = patients[["patient_id", "sex", "birth_date"]].copy()
    # ages above 89 are grouped as 90 (HIPAA Safe Harbor style)
    f["age"] = ((as_of - f["birth_date"]).dt.days // 365.25).astype(int).clip(upper=90)

    by = observations.sort_values("effective_time").groupby(["patient_id", "name"])["value"]
    latest = by.last().unstack().reindex(columns=["bmi", "hba1c"]).add_suffix("_latest")
    mean = by.mean().unstack().reindex(columns=["glucose", "systolic_bp"]).add_suffix("_mean")
    f = f.join(latest, on="patient_id").join(mean, on="patient_id")

    f["encounter_count"] = f["patient_id"].map(encounters.groupby("patient_id").size()).fillna(0).astype(int)
    diabetic_ids = diagnoses.loc[diagnoses["code"].astype(str).str.startswith(DIABETES_ICD10_PREFIX), "patient_id"]
    f["has_diabetes"] = f["patient_id"].isin(diabetic_ids)

    f.insert(0, "pseudo_id", f["patient_id"].map(lambda pid: pseudonymize(pid, key)))
    f = f.drop(columns=["patient_id", "birth_date"])
    leaked = set(PII_COLUMNS) & set(f.columns)
    if leaked:
        raise RuntimeError(f"Direct identifiers would leak into Gold: {sorted(leaked)}")
    return f


def cohort_summary(features: pd.DataFrame) -> pd.DataFrame:
    bands = pd.cut(features["age"], [0, 40, 60, 75, 200], labels=["18-39", "40-59", "60-74", "75+"], right=False)
    c = (features.assign(age_band=bands)
         .groupby(["age_band", "sex"], observed=True)
         .agg(patients=("pseudo_id", "size"), diabetes=("has_diabetes", "sum"), bmi_mean=("bmi_latest", "mean"))
         .reset_index())
    for col in ["patients", "diabetes"]:
        c[col] = c[col].astype("Int64").mask(c[col] < MIN_CELL_SIZE)
    c["diabetes_prevalence"] = (c["diabetes"] / c["patients"]).round(3)
    c["bmi_mean"] = c["bmi_mean"].round(1).mask(c["patients"].isna())
    return c


def build(data_dir, key: bytes, as_of=None) -> dict[str, int]:
    silver = Path(data_dir) / "silver"
    t = {n: pd.read_parquet(silver / f"{n}.parquet") for n in ["patients", "encounters", "diagnoses", "observations"]}
    features = patient_features(t["patients"], t["encounters"], t["diagnoses"], t["observations"], key, as_of)
    cohort = cohort_summary(features)
    write_parquet(features, Path(data_dir) / "gold" / "patient_features.parquet")
    write_parquet(cohort, Path(data_dir) / "gold" / "cohort_summary.parquet")
    result = {"patient_features_rows": len(features), "cohort_cells": len(cohort),
              "diabetes_cases": int(features["has_diabetes"].sum())}
    log.info("gold built", extra={"ctx": result})
    return result
