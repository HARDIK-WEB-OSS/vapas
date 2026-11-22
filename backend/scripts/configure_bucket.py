import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from vapas.config import LOCAL_ENVS, get_settings
from vapas.storage.object_store import (
    allow_browser_uploads,
    create_s3_client,
    ensure_bucket,
    expire_raw_uploads,
    raw_lifecycle_days,
)

ATTEMPTS = 30
WAIT_SECONDS = 2.0


def main() -> int:
    settings = get_settings()
    client = create_s3_client(settings)
    bucket = settings.s3_bucket_raw
    for attempt in range(1, ATTEMPTS + 1):
        try:
            if settings.app_env in LOCAL_ENVS:
                ensure_bucket(client, bucket)
            allow_browser_uploads(client, bucket, settings.public_app_url)
            expire_raw_uploads(client, bucket)
            days = raw_lifecycle_days(client, bucket)
        except (BotoCoreError, ClientError) as error:
            print(f"object store not ready (attempt {attempt}): {type(error).__name__}", file=sys.stderr)
            time.sleep(WAIT_SECONDS)
            continue
        print(
            f"bucket {bucket}: browser uploads from {settings.public_app_url}, raw uploads expire after {days} day(s)"
        )
        return 0 if days is not None else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
