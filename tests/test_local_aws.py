"""Smoke test against MiniStack. Run: python -m pytest -m aws_local"""
import os
import time
import urllib.request
import uuid

import pytest

from config import aws

pytestmark = pytest.mark.aws_local
LOCAL_DEFAULT = "http://localhost:4566"  # test-only default; config.aws never assumes an endpoint


@pytest.fixture
def local_endpoint(monkeypatch):
    endpoint = os.environ.get("AWS_ENDPOINT_URL") or LOCAL_DEFAULT
    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    try:
        urllib.request.urlopen(f"{endpoint}/_ministack/health", timeout=3)
    except OSError as exc:
        pytest.fail(f"MiniStack not reachable at {endpoint} ({exc}). Start it: docker compose up -d ministack", pytrace=False)
    return endpoint


def test_s3_and_dynamodb_roundtrip(local_endpoint):
    s3, ddb = aws.client("s3"), aws.client("dynamodb")
    assert s3.meta.endpoint_url == local_endpoint
    name = f"smoke-{uuid.uuid4().hex[:8]}"

    s3.create_bucket(Bucket=name)
    try:
        s3.put_object(Bucket=name, Key="hello.txt", Body=b"synthetic only")
        assert s3.get_object(Bucket=name, Key="hello.txt")["Body"].read() == b"synthetic only"
    finally:
        s3.delete_object(Bucket=name, Key="hello.txt")
        s3.delete_bucket(Bucket=name)

    ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                     KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}])
    try:
        ddb.get_waiter("table_exists").wait(TableName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 10})
        ddb.put_item(TableName=name, Item={"pk": {"S": "run-1"}, "status": {"S": "ok"}})
        item = ddb.get_item(TableName=name, Key={"pk": {"S": "run-1"}})["Item"]
        assert item["status"]["S"] == "ok"
    finally:
        ddb.delete_table(TableName=name)

    assert name not in [b["Name"] for b in s3.list_buckets()["Buckets"]]
    assert name not in ddb.list_tables()["TableNames"]


def test_athena_queries_real_rows_from_s3(local_endpoint):
    s3, glue, athena = aws.client("s3"), aws.client("glue"), aws.client("athena")
    name = f"athena_{uuid.uuid4().hex[:8]}"
    bucket = name.replace("_", "-")
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="cohort/data.csv", Body=b"age_band,patients\n18-39,146\n40-59,133\n")

    def query(sql, database=None):
        context = {"QueryExecutionContext": {"Database": database}} if database else {}
        qid = athena.start_query_execution(
            QueryString=sql, ResultConfiguration={"OutputLocation": f"s3://{bucket}/results/"}, **context)["QueryExecutionId"]
        for _ in range(30):
            status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)
        assert status["State"] == "SUCCEEDED", status
        rows = athena.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]
        return [[c.get("VarCharValue") for c in r["Data"]] for r in rows]

    # tables are defined in the Glue Data Catalog, as Terraform will do in the real account
    glue.create_database(DatabaseInput={"Name": name})
    glue.create_table(DatabaseName=name, TableInput={
        "Name": "cohort", "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "csv", "skip.header.line.count": "1"},
        "StorageDescriptor": {
            "Columns": [{"Name": "age_band", "Type": "string"}, {"Name": "patients", "Type": "int"}],
            "Location": f"s3://{bucket}/cohort/",
            "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                          "Parameters": {"field.delim": ","}},
        },
    })
    try:
        rows = query("SELECT age_band, patients FROM cohort ORDER BY age_band", name)
        assert rows == [["age_band", "patients"], ["18-39", "146"], ["40-59", "133"]]
        # the mock engine cannot aggregate, so a correct SUM proves real query execution
        assert query("SELECT SUM(patients) AS total FROM cohort", name) == [["total"], ["279"]]
    finally:
        glue.delete_database(Name=name)
        for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)


def test_unset_endpoint_targets_real_aws(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert aws.client("s3").meta.endpoint_url == "https://s3.amazonaws.com"
