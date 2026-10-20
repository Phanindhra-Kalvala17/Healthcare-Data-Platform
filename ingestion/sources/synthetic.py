"""Synthetic EHR, hospital and lab extracts with deliberate defects. Development data only, no real patients."""
from pathlib import Path

import numpy as np
import pandas as pd

from healthcare_models.schemas import SOURCE_FILES

FIRST_NAMES = ["Aarav", "Priya", "Rahul", "Ananya", "Vikram", "Sneha", "Arjun", "Kavya", "John", "Maria"]
LAST_NAMES = ["Sharma", "Reddy", "Patel", "Iyer", "Khan", "Singh", "Nair", "Gupta", "Smith", "Garcia"]
OTHER_DIAGNOSES = ["I10", "J06.9", "M54.5", "Z00.00", "E78.5"]


def generate(landing_dir, n_patients: int = 1000, seed: int = 42, as_of: str = "2026-01-01") -> dict[str, str]:
    rng = np.random.default_rng(seed)
    as_of = pd.Timestamp(as_of, tz="UTC")
    patients, encounters, observations = [], [], []

    for i in range(n_patients):
        pid = f"P{i:07d}"
        age = int(rng.integers(18, 90))
        bmi = float(np.clip(rng.normal(27, 5), 15, 55))
        diabetic = rng.random() < 1 / (1 + np.exp(9 - 0.06 * age - 0.15 * bmi))
        birth = as_of - pd.Timedelta(days=int(age * 365.25 + rng.integers(0, 365)))
        patients.append({
            "patient_id": pid,
            "first_name": rng.choice(FIRST_NAMES),
            "last_name": rng.choice(LAST_NAMES),
            "birth_date": birth.date().isoformat(),
            "sex": rng.choice(["M", "F", "male", "female"]),
            "phone": f"+91-9{rng.integers(0, 10**9):09d}",
            "postal_code": str(rng.integers(110000, 860000)),
        })

        for e in range(int(rng.poisson(3)) + 1):
            eid = f"{pid}-E{e:02d}"
            start = as_of - pd.Timedelta(minutes=int(rng.integers(1, 2 * 365 * 24 * 60)))
            iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            # the hospital system sometimes reports local IST time instead of UTC
            start_str = iso if rng.random() < 0.8 else (start + pd.Timedelta(hours=5.5)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
            dx = [str(c) for c in rng.choice(OTHER_DIAGNOSES, size=int(rng.integers(0, 3)), replace=False)]
            if diabetic and rng.random() < 0.7:
                dx.append("E11.9")
            encounters.append({
                "encounter_id": eid, "patient_id": pid, "start_time": start_str,
                "encounter_type": rng.choice(["outpatient", "inpatient", "emergency"], p=[0.7, 0.2, 0.1]),
                "facility_id": f"F{rng.integers(1, 6):03d}", "diagnosis_codes": dx,
            })

            def obs(code, value, unit):
                observations.append({
                    "observation_id": f"{eid}-{code}", "patient_id": pid, "encounter_id": eid,
                    "code": code, "value": str(round(value, 1)), "unit": unit, "effective_time": iso,
                })

            obs("39156-5", bmi + rng.normal(0, 0.5), "kg/m2")
            obs("8480-6", rng.normal(118 + 0.4 * (age - 40) + (8 if diabetic else 0), 14), "mmHg")
            if rng.random() < 0.7:
                glucose = rng.normal(165, 40) if diabetic else rng.normal(95, 12)
                if rng.random() < 0.3:
                    obs("2345-7", glucose / 18.016, "mmol/L")
                else:
                    obs("2345-7", glucose, "mg/dL")
            if rng.random() < 0.4:
                obs("4548-4", rng.normal(8.0, 1.2) if diabetic else rng.normal(5.4, 0.4), "%")

    p, e, o = pd.DataFrame(patients), pd.DataFrame(encounters), pd.DataFrame(observations)

    # defects the Silver layer has to catch
    p.loc[p.sample(frac=0.01, random_state=seed).index, "birth_date"] = ""
    p.loc[p.sample(frac=0.005, random_state=seed + 1).index, "sex"] = "?"
    p = pd.concat([p, p.sample(frac=0.02, random_state=seed)], ignore_index=True)
    e.loc[e.sample(frac=0.005, random_state=seed).index, "start_time"] = "not-a-date"
    orphans = e.sample(n=min(3, len(e)), random_state=seed).assign(patient_id="P9999999")
    e = pd.concat([e, orphans.assign(encounter_id=orphans.encounter_id + "-X")], ignore_index=True)
    o.loc[o.sample(frac=0.005, random_state=seed).index, "value"] = "N/A"
    bmi_rows = o[o.code == "39156-5"].sample(frac=0.003, random_state=seed).index
    o.loc[bmi_rows, "value"] = "400"
    o = pd.concat([o, o.sample(frac=0.02, random_state=seed)], ignore_index=True)

    out = Path(landing_dir) / f"batch_seed{seed}"
    out.mkdir(parents=True, exist_ok=True)
    paths = {t: out / f for t, f in SOURCE_FILES.items()}
    p.to_csv(paths["patients"], index=False)
    e.to_json(paths["encounters"], orient="records", indent=1)
    o.to_csv(paths["observations"], index=False)
    return {t: str(path) for t, path in paths.items()}
