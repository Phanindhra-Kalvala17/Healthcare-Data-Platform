# Healthcare Data Platform

Local MVP of a healthcare data pipeline: synthetic EHR, hospital and lab data flows through a **Bronze → Silver → Gold** data lake with validation, quarantine, pseudonymization, quality reports and a monitoring dashboard.

> Synthetic data only. Do not load real patient data into this project without authorization, a privacy assessment and the AWS controls planned in Phase 2. Implementing security controls does not by itself make a deployment HIPAA or DPDP Act compliant.

Architecture, design decisions and data model: [docs/architecture.md](docs/architecture.md)

## Quick start (local)

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set HDP_PSEUDONYMIZATION_KEY:
python -c "import secrets; print(secrets.token_hex(32))"

python -m orchestration.pipeline --generate 1000   # generate + run the full pipeline
streamlit run dashboard/app.py                     # http://localhost:8501
python -m pytest                                   # 16 tests
```

Run the pipeline again without `--generate` to process only new landing files (already-ingested files are skipped). Run with `--generate N --seed S` and a new seed to simulate another source batch.

## Docker

```bash
cp .env.example .env    # set the key
docker compose run --rm pipeline
docker compose up dashboard   # http://localhost:8501
```

## Local testing

| Where | What | Command |
|---|---|---|
| **Locally, always** | Pipeline logic (Bronze/Silver/Gold as plain pandas functions), dashboard, IAM policy files render to valid JSON | `python -m pytest` |
| **Locally, with MiniStack** ([LOCAL_AWS.md](LOCAL_AWS.md)) | S3 + DynamoDB round trip, Athena SQL over S3 via the Glue catalog (real results, `:full` image) | `docker compose up -d ministack` then `python -m pytest -m aws_local` |
| **Skipped by default** | Tests marked `spark` (need a real Spark session) | Not run locally |
| **Dev AWS account only** | Glue Spark jobs; `terraform plan`; IAM Access Analyzer policy validation; any check that depends on IAM permissions | see below |

**Spark / Glue:** job logic lives in plain Python functions that take and return DataFrames (`processing/silver.py`, `processing/gold.py`), so it's unit-tested locally without Spark. Spark jobs themselves run only in the real dev AWS account. `docker.sock` is never mounted into any container, because that would give the container full control of the host's Docker.

**IAM (dev account only):** IAM can't be validated locally, and MiniStack doesn't enforce it.

```powershell
aws sso login --profile hdp-dev
powershell -File scripts/plan_dev.ps1                       # terraform init + validate + plan, never applies
$env:AWS_PROFILE = "hdp-dev"; python -m scripts.validate_iam_policies
```

`validate_iam_policies` sends every policy in `infrastructure/terraform/policies/` to IAM Access Analyzer `ValidatePolicy`. It exits non-zero on `ERROR` or `SECURITY_WARNING` findings. The CLI equivalent for one policy is `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://policy.json`. In the console, use **IAM → Policies → Create policy → JSON** to see the same findings. Both scripts refuse to talk to MiniStack: `plan_dev.ps1` drops `AWS_ENDPOINT_URL`, and the validator exits if it's set.

## Data layout (`data/`, gitignored)

| Path | Contents |
|---|---|
| `landing/` | Incoming source files |
| `bronze/<table>/*.parquet` | Raw values plus lineage columns, one file per source file; `_manifest.json` records ingested hashes |
| `silver/*.parquet` | Validated, typed, deduplicated `patients`, `encounters`, `diagnoses`, `observations` |
| `quarantine/*.parquet` | Rejected rows with `_reject_reason` |
| `gold/` | `patient_features` (pseudonymized) and `cohort_summary` (cells under 5 suppressed) |
| `reports/quality_latest.json` | Per-table quality report |
| `runs/*.json`, `alerts.jsonl` | Run records and alerts |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `HDP_PSEUDONYMIZATION_KEY must be set...` | Put a 32+ character secret in `.env` |
| `Bronze is missing data for: [...]` | Nothing in `data/landing` yet: run with `--generate N` |
| Run status `succeeded_with_quality_alerts` | A table's quality score fell below `HDP_QUALITY_THRESHOLD`. Check `data/quarantine/` and `data/alerts.jsonl` |
| Dashboard says "No pipeline runs yet" | Run the pipeline first, using the same `HDP_DATA_DIR` |

## Status

**Phase 1 (local MVP): implemented and tested.** Synthetic generator, idempotent Bronze ingestion, Silver validation/normalization/dedupe/quarantine, Gold pseudonymized features and cohort, orchestration with retries, run records and alerts, Streamlit dashboard, Docker.

**Not yet built:**
- **Phase 2:** Terraform (S3, KMS, Glue, Lambda, Step Functions, IAM, CloudTrail, CloudWatch, SNS), dev/staging/prod configs, CI/CD.
- **Phase 3:** ML baseline (diabetes risk) with patient-level split, MLflow tracking, calibration and bias checks, predictions stored separately, model metrics in the dashboard.
- **Phase 4:** PySpark/Glue, Iceberg incremental MERGE, streaming (Kinesis), FHIR API connector, lineage, threat model, cost estimates, load tests.

**Known limitations:**
- Silver is fully rebuilt each run, which is fine at thousands of rows but not at scale.
- pandas runs on a single node.
- Only patients, encounters, diagnoses and observations are modeled.
- The `.env` parser is minimal.
- Alerts are local files.
- There is no access control locally; it is planned through IAM.
