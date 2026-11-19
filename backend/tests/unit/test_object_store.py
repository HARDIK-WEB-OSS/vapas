from collections.abc import Iterator

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from mypy_boto3_s3 import S3Client

from vapas.storage.object_store import ensure_bucket


@pytest.fixture
def client() -> S3Client:
    return boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="k", aws_secret_access_key="s", endpoint_url="http://s3.test"
    )


@pytest.fixture
def stub(client: S3Client) -> Iterator[Stubber]:
    with Stubber(client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def test_existing_bucket_is_left_alone(client: S3Client, stub: Stubber) -> None:
    stub.add_response("head_bucket", {}, {"Bucket": "vapas-raw"})
    assert ensure_bucket(client, "vapas-raw") is False


def test_missing_bucket_is_created(client: S3Client, stub: Stubber) -> None:
    stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    stub.add_response("create_bucket", {}, {"Bucket": "vapas-raw"})
    assert ensure_bucket(client, "vapas-raw") is True


def test_other_errors_are_not_swallowed(client: S3Client, stub: Stubber) -> None:
    stub.add_client_error("head_bucket", service_error_code="403", http_status_code=403)
    with pytest.raises(ClientError):
        ensure_bucket(client, "vapas-raw")
