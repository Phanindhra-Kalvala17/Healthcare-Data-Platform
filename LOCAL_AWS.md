# Local AWS with MiniStack

[MiniStack](https://pypi.org/project/ministack/) emulates AWS on one port (4566), so AWS code and tests run without a real account.

## How it switches

All AWS clients come from `config.aws.client(service)`:

| `AWS_ENDPOINT_URL` | Behaviour |
|---|---|
| unset | Real AWS, default boto3 credential chain. Unchanged from before. |
| set (e.g. `http://localhost:4566`) | That endpoint, with dummy credentials `test`/`test` and region `us-east-1`. Real credentials are never used. |

Keep real AWS credentials out of the repo: use `aws configure` / SSO profiles or an untracked `.env`. Never commit or print them.

## Start

```bash
docker compose up -d ministack
curl http://localhost:4566/_ministack/health     # JSON listing services; "auth": "disabled"
```

The image is pinned to `ministackorg/ministack:1.5.29-full`, the same build as `:full` (about 440 MB). The full edition includes DuckDB, so Athena runs real SQL. docker.sock is **never** mounted (see the README "Local testing" section). Stop it with `docker compose stop ministack`.

## Run tests against it

```bash
.venv/Scripts/python -m pytest -m aws_local -v    # S3 + DynamoDB round trip, Athena over S3
.venv/Scripts/python -m pytest                    # normal suite, AWS tests excluded
```

The smoke test uses `AWS_ENDPOINT_URL`, or `http://localhost:4566` if unset. It fails with `MiniStack not reachable at ...` when the emulator is down.

To point your own code or the pipeline at MiniStack, set `AWS_ENDPOINT_URL=http://localhost:4566` in your shell or `.env`.

## Known limits

**Verified here:**
- S3 and DynamoDB round trips work (smoke test).
- Athena returns real rows and aggregates (`SUM`) from a CSV in S3. The table must be defined in the **Glue Data Catalog**, the same way Terraform will define it. Athena DDL (`CREATE DATABASE`, `CREATE EXTERNAL TABLE`) fails, and there is no `default` database.
- The health endpoint reports all of these as "available": s3, dynamodb, glue, athena, lambda, states (Step Functions), kms, iam, sts, cloudtrail, monitoring (CloudWatch), logs, sns, kinesis, secretsmanager.
- IAM authorization is off by default (`"auth": "disabled"`), so permission bugs will not show up locally.

**From MiniStack's docs, not yet verified here.** Treat these as gaps until a test proves otherwise:

| Service | Limit |
|---|---|
| Glue | Catalog works (verified via the Athena test). Spark jobs would need docker.sock, which we never mount, so they run only in the dev account. |
| IAM | Policies are stored but not enforced. Validate in the dev account instead (README "Local testing"). Do not rely on `AUTH=true`. |
| STS | Only a handful of operations (e.g. GetCallerIdentity, AssumeRole). |
| CloudTrail | In-memory; recording is opt-in (`CLOUDTRAIL_RECORDING=1`). |
| KMS | Grants are stored but not evaluated. |
| S3 | State is shared across regions (not region-isolated). |
| Persistence | State is in-memory and lost on container restart unless persistence is enabled (e.g. `S3_PERSIST=1`). |

"Available" in the health check means the API answers, not that behaviour matches AWS. Anything that depends on IAM denial, Athena query results or Glue Spark must still be tested in a real (dev) AWS account.
