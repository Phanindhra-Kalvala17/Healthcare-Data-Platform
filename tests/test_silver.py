import pandas as pd

from processing.silver import clean_encounters, clean_observations, clean_patients
from tests.conftest import bronze


def patient(pid="P1", **kw):
    return {"patient_id": pid, "first_name": "A", "last_name": "B", "birth_date": "1970-05-01", "sex": "M"} | kw


def test_patients_normalize_sex_and_reject_invalid_rows():
    raw = bronze([patient("P1", sex="female"), patient("P2", sex="?"), patient("P3", birth_date=""),
                  patient("P4", birth_date="2999-01-01"), patient("P5", birth_date="05/01/1970")])
    valid, rejected, _ = clean_patients(raw)
    assert valid["patient_id"].tolist() == ["P1"]
    assert valid["sex"].tolist() == ["F"]
    assert dict(zip(rejected.patient_id, rejected._reject_reason)) == {
        "P2": "invalid_sex", "P3": "missing_birth_date", "P4": "invalid_birth_date", "P5": "invalid_birth_date"}


def test_later_batch_correction_wins_over_earlier_record():
    raw = pd.concat([bronze([patient("P1", last_name="Old")], "2026-01-01"),
                     bronze([patient("P1", last_name="New")], "2026-02-01")])
    valid, _, dups = clean_patients(raw)
    assert valid["last_name"].tolist() == ["New"]
    assert dups == 1


def test_encounters_normalize_timezones_and_quarantine_orphans():
    raw = bronze([
        {"encounter_id": "E1", "patient_id": "P1", "start_time": "2025-03-04T10:00:00Z", "encounter_type": "outpatient", "diagnosis_codes": ["E11.9", "I10"]},
        {"encounter_id": "E2", "patient_id": "P1", "start_time": "2025-03-04T15:30:00+05:30", "encounter_type": "outpatient", "diagnosis_codes": []},
        {"encounter_id": "E3", "patient_id": "P1", "start_time": "not-a-date", "encounter_type": "inpatient", "diagnosis_codes": []},
        {"encounter_id": "E4", "patient_id": "P404", "start_time": "2025-03-04T10:00:00Z", "encounter_type": "inpatient", "diagnosis_codes": []},
    ])
    valid, diagnoses, rejected, _ = clean_encounters(raw, pd.Series(["P1"]))
    assert valid.set_index("encounter_id")["start_time"].nunique() == 1  # same instant in UTC
    assert dict(zip(rejected.encounter_id, rejected._reject_reason)) == {"E3": "invalid_start_time", "E4": "patient_not_in_silver"}
    assert sorted(diagnoses["code"]) == ["E11.9", "I10"]


def obs(oid, code, value, unit):
    return {"observation_id": oid, "patient_id": "P1", "encounter_id": "E1", "code": code,
            "value": value, "unit": unit, "effective_time": "2025-03-04T10:00:00Z"}


def test_observations_convert_units_and_reject_bad_values():
    raw = bronze([obs("O1", "2345-7", "5.5", "mmol/L"), obs("O2", "2345-7", "99", "mg/dL"),
                  obs("O3", "39156-5", "N/A", "kg/m2"), obs("O4", "39156-5", "400", "kg/m2"),
                  obs("O5", "2345-7", "5", "furlongs"), obs("O6", "9999-9", "1", "x"),
                  obs("O2", "2345-7", "99", "mg/dL")])
    valid, rejected, dups = clean_observations(raw, pd.Series(["P1"]))
    values = valid.set_index("observation_id")["value"].to_dict()
    assert values == {"O1": round(5.5 * 18.016, 2), "O2": 99.0}
    assert set(valid["unit"]) == {"mg/dL"}
    assert dups == 1
    assert dict(zip(rejected.observation_id, rejected._reject_reason)) == {
        "O3": "invalid_value", "O4": "implausible_value", "O5": "unknown_unit", "O6": "unknown_code"}
