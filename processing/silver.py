"""Silver: validate, normalize and deduplicate Bronze data. Invalid rows go to quarantine with a reason."""
import json
import logging
from pathlib import Path

import pandas as pd

from data_quality.checks import latest_per_key, missing, split_valid, table_report
from healthcare_models.schemas import OBSERVATION_CODES, REQUIRED, SEX_MAP, UNIT_CONVERSIONS
from ingestion.batch import read_bronze, write_parquet

log = logging.getLogger(__name__)


def _required_checks(df, table):
    return [(f"missing_{c}", missing(df, c)) for c in REQUIRED[table]]


def clean_patients(df: pd.DataFrame):
    df = df.reset_index(drop=True)
    sex = df["sex"].astype("string").str.strip().str.lower().map(SEX_MAP)
    birth = pd.to_datetime(df["birth_date"], format="%Y-%m-%d", errors="coerce")
    valid, rejected = split_valid(df, _required_checks(df, "patients") + [
        ("invalid_sex", sex.isna()),
        ("invalid_birth_date", birth.isna() | (birth > pd.Timestamp.now())),
    ])
    valid = valid.assign(sex=sex[valid.index], birth_date=birth[valid.index])
    valid, dups = latest_per_key(valid, "patient_id")
    return valid, rejected, dups


def clean_encounters(df: pd.DataFrame, patient_ids: pd.Series):
    df = df.reset_index(drop=True)
    start = pd.to_datetime(df["start_time"], format="ISO8601", utc=True, errors="coerce")
    valid, rejected = split_valid(df, _required_checks(df, "encounters") + [
        ("invalid_start_time", start.isna() | (start > pd.Timestamp.now(tz="UTC"))),
        ("patient_not_in_silver", ~df["patient_id"].isin(patient_ids)),
    ])
    valid = valid.assign(start_time=start[valid.index])
    valid, dups = latest_per_key(valid, "encounter_id")
    diagnoses = (
        valid[["encounter_id", "patient_id", "start_time", "diagnosis_codes"]]
        .explode("diagnosis_codes")
        .dropna(subset=["diagnosis_codes"])
        .rename(columns={"diagnosis_codes": "code", "start_time": "recorded_at"})
        .assign(code_system="ICD-10")
    )
    return valid.drop(columns="diagnosis_codes"), diagnoses, rejected, dups


def clean_observations(df: pd.DataFrame, patient_ids: pd.Series):
    df = df.reset_index(drop=True)
    value = pd.to_numeric(df["value"], errors="coerce")
    factor = (df["code"].astype("string") + "|" + df["unit"].astype("string")).map(UNIT_CONVERSIONS).astype(float)
    canonical = value * factor
    lo = df["code"].map({c: s["range"][0] for c, s in OBSERVATION_CODES.items()})
    hi = df["code"].map({c: s["range"][1] for c, s in OBSERVATION_CODES.items()})
    when = pd.to_datetime(df["effective_time"], format="ISO8601", utc=True, errors="coerce")
    valid, rejected = split_valid(df, _required_checks(df, "observations") + [
        ("unknown_code", ~df["code"].isin(list(OBSERVATION_CODES))),
        ("invalid_value", value.isna()),
        ("unknown_unit", factor.isna()),
        ("implausible_value", (canonical < lo) | (canonical > hi)),
        ("invalid_effective_time", when.isna()),
        ("patient_not_in_silver", ~df["patient_id"].isin(patient_ids)),
    ])
    idx = valid.index
    valid = valid.assign(
        source_value=valid["value"], source_unit=valid["unit"],
        value=canonical[idx].round(2),
        unit=valid["code"].map({c: s["unit"] for c, s in OBSERVATION_CODES.items()}),
        name=valid["code"].map({c: s["name"] for c, s in OBSERVATION_CODES.items()}),
        code_system="LOINC", effective_time=when[idx],
    )
    valid, dups = latest_per_key(valid, "observation_id")
    return valid, rejected, dups


def build(data_dir) -> dict[str, dict]:
    # shortcut: full rebuild from all Bronze files each run; move to incremental MERGE (Iceberg) in Phase 4
    data_dir = Path(data_dir)
    raw = {t: read_bronze(data_dir, t) for t in REQUIRED}
    if any(df.empty for df in raw.values()):
        raise ValueError(f"Bronze is missing data for: {[t for t, df in raw.items() if df.empty]}")

    patients, rej_p, dup_p = clean_patients(raw["patients"])
    encounters, diagnoses, rej_e, dup_e = clean_encounters(raw["encounters"], patients["patient_id"])
    observations, rej_o, dup_o = clean_observations(raw["observations"], patients["patient_id"])

    outputs = {"patients": patients, "encounters": encounters, "diagnoses": diagnoses, "observations": observations}
    for table, df in outputs.items():
        write_parquet(df, data_dir / "silver" / f"{table}.parquet")

    reports = {}
    for table, valid, rejected, dups in [("patients", patients, rej_p, dup_p),
                                         ("encounters", encounters, rej_e, dup_e),
                                         ("observations", observations, rej_o, dup_o)]:
        write_parquet(rejected, data_dir / "quarantine" / f"{table}.parquet")
        reports[table] = table_report(table, raw[table], valid, rejected, dups, REQUIRED[table])
        log.info("silver table built", extra={"ctx": reports[table]})

    report_dir = data_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "quality_latest.json").write_text(json.dumps(reports, indent=1))
    return reports
