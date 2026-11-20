from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from vapas.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

MISSING_BUCKET_CODES = frozenset({"404", "NoSuchBucket", "NotFound"})
DELETE_BATCH = 1000
USER_PREFIXES = ("raw/",)


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


def user_prefixes(user_id: str) -> list[str]:
    return [f"{prefix}{user_id}/" for prefix in USER_PREFIXES]


def delete_prefix(client: S3Client, bucket: str, prefix: str) -> int:
    deleted = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys: list[ObjectIdentifierTypeDef] = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        for start in range(0, len(keys), DELETE_BATCH):
            batch = keys[start : start + DELETE_BATCH]
            client.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            deleted += len(batch)
    return deleted


async def delete_user_objects(client: S3Client, bucket: str, user_id: str) -> int:
    counts = [await asyncio.to_thread(delete_prefix, client, bucket, p) for p in user_prefixes(user_id)]
    return sum(counts)


PRESIGN_EXPIRY_SECONDS = 300
RAW_PREFIX = "raw/"


def raw_key(user_id: str, statement_id: str) -> str:
    return f"{RAW_PREFIX}{user_id}/{statement_id}"


def create_presign_client(settings: Settings) -> S3Client:
    public = settings.s3_public_endpoint_url or settings.s3_endpoint_url
    return create_s3_client(settings.model_copy(update={"s3_endpoint_url": public}))


def presign_upload(client: S3Client, bucket: str, key: str, content_type: str) -> str:
    params = {"Bucket": bucket, "Key": key, "ContentType": content_type}
    return client.generate_presigned_url("put_object", Params=params, ExpiresIn=PRESIGN_EXPIRY_SECONDS)


def object_size(client: S3Client, bucket: str, key: str) -> int | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in MISSING_BUCKET_CODES | {"NoSuchKey"}:
            return None
        raise


def read_object(client: S3Client, bucket: str, key: str) -> bytes | None:
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in MISSING_BUCKET_CODES | {"NoSuchKey"}:
            return None
        raise


def delete_object(client: S3Client, bucket: str, key: str) -> None:
    client.delete_object(Bucket=bucket, Key=key)


def stale_raw_keys(client: S3Client, bucket: str, older_than: datetime) -> list[str]:
    keys: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=RAW_PREFIX):
        keys.extend(item["Key"] for item in page.get("Contents", []) if item["LastModified"] < older_than)
    return keys


def delete_keys(client: S3Client, bucket: str, keys: list[str]) -> int:
    for start in range(0, len(keys), DELETE_BATCH):
        batch: list[ObjectIdentifierTypeDef] = [{"Key": key} for key in keys[start : start + DELETE_BATCH]]
        client.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
    return len(keys)
