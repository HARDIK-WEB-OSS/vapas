from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from vapas.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

MISSING_BUCKET_CODES = frozenset({"404", "NoSuchBucket", "NotFound"})


def create_s3_client(settings: Settings) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
    )


def ensure_bucket(client: S3Client, bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in MISSING_BUCKET_CODES:
            raise
        client.create_bucket(Bucket=bucket)
        return True
    return False


async def ping_bucket(client: S3Client, bucket: str) -> bool:
    await asyncio.to_thread(client.head_bucket, Bucket=bucket)
    return True
