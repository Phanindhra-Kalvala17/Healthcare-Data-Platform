"""Validate this repo's IAM policies with AWS IAM Access Analyzer.

Needs real dev-account credentials (e.g. after `aws sso login --profile hdp-dev`, with AWS_PROFILE=hdp-dev).
IAM cannot be emulated locally, so this refuses to run against MiniStack.
Usage: python -m scripts.validate_iam_policies
"""
import os
import sys
from pathlib import Path
from string import Template

from config import aws

POLICY_DIR = Path(__file__).resolve().parent.parent / "infrastructure" / "terraform" / "policies"

# Placeholder ARNs stand in for values Terraform only knows after apply; validation checks grammar and risk, not ARNs.
EXAMPLE_VALUES = {
    "account_id": "111122223333",
    "bucket_arn": "arn:aws:s3:::hdp-dev-lake-111122223333",
    "kms_key_arn": "arn:aws:kms:ap-south-1:111122223333:key/00000000-0000-0000-0000-000000000000",
}

POLICIES = {
    "pipeline-data-lake.json.tftpl": {"policyType": "IDENTITY_POLICY"},
    "pipeline-trust.json.tftpl": {"policyType": "RESOURCE_POLICY",
                            "validatePolicyResourceType": "AWS::IAM::AssumeRolePolicyDocument"},
    "lake-bucket.json.tftpl": {"policyType": "RESOURCE_POLICY", "validatePolicyResourceType": "AWS::S3::Bucket"},
}

BLOCKING = {"ERROR", "SECURITY_WARNING"}


def render(name: str) -> str:
    return Template((POLICY_DIR / name).read_text()).substitute(EXAMPLE_VALUES)


def main() -> int:
    if os.environ.get("AWS_ENDPOINT_URL"):
        sys.exit("Unset AWS_ENDPOINT_URL: Access Analyzer must run against the real dev account, not MiniStack.")
    analyzer = aws.client("accessanalyzer")
    failed = False
    for name, kwargs in POLICIES.items():
        pages = analyzer.get_paginator("validate_policy").paginate(policyDocument=render(name), **kwargs)
        findings = [f for page in pages for f in page["findings"]]
        for f in findings:
            print(f"{name}: {f['findingType']} {f['issueCode']}: {f['findingDetails']}")
            failed |= f["findingType"] in BLOCKING
        if not findings:
            print(f"{name}: no findings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
