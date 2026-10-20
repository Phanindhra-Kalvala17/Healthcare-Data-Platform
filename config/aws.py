"""Single place where boto3 clients are created.

AWS_ENDPOINT_URL unset -> real AWS with the default credential chain (unchanged behaviour).
AWS_ENDPOINT_URL set   -> local emulator (MiniStack) with dummy credentials, never real ones.
"""
import os

import boto3


def client(service: str):
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        return boto3.client(service)
    return boto3.client(service, endpoint_url=endpoint, region_name="us-east-1",
                        aws_access_key_id="test", aws_secret_access_key="test")
