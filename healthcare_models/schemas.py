"""Logical data model for the source extracts. FHIR mappings are documented in docs/architecture.md."""

# table -> landing file name produced by each source system
SOURCE_FILES = {
    "patients": "ehr_patients.csv",
    "encounters": "hms_encounters.json",
    "observations": "lis_observations.csv",
}

REQUIRED = {
    "patients": ["patient_id", "birth_date", "sex"],
    "encounters": ["encounter_id", "patient_id", "start_time", "encounter_type"],
    "observations": ["observation_id", "patient_id", "code", "value", "unit", "effective_time"],
}

# Direct identifiers that must never reach the Gold zone (birth_date is reduced to age).
PII_COLUMNS = ["patient_id", "first_name", "last_name", "phone", "postal_code", "birth_date"]

SEX_MAP = {"m": "M", "male": "M", "f": "F", "female": "F", "u": "U", "unknown": "U"}

# LOINC code -> feature name, canonical UCUM unit, plausible range in canonical unit
OBSERVATION_CODES = {
    "2345-7": {"name": "glucose", "unit": "mg/dL", "range": (20, 1000)},
    "4548-4": {"name": "hba1c", "unit": "%", "range": (3, 20)},
    "8480-6": {"name": "systolic_bp", "unit": "mm[Hg]", "range": (50, 300)},
    "39156-5": {"name": "bmi", "unit": "kg/m2", "range": (10, 80)},
}

# "code|source unit" -> factor to canonical unit
UNIT_CONVERSIONS = {f"{code}|{spec['unit']}": 1.0 for code, spec in OBSERVATION_CODES.items()} | {
    "2345-7|mmol/L": 18.016,
    "8480-6|mmHg": 1.0,
}

DIABETES_ICD10_PREFIX = "E11"
