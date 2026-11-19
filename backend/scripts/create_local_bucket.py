import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from vapas.config import get_settings
from vapas.storage.object_store import create_s3_client, ensure_bucket

LOCAL_ENVS = frozenset({"local", "test"})
ATTEMPTS = 30
WAIT_SECONDS = 2.0


def main() -> int:
    settings = get_settings()
    if settings.app_env not in LOCAL_ENVS:
        print(f"refusing to create buckets when APP_ENV={settings.app_env}", file=sys.stderr)
        return 1
    client = create_s3_client(settings)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            created = ensure_bucket(client, settings.s3_bucket_raw)
        except (BotoCoreError, ClientError) as error:
            print(f"object store not ready (attempt {attempt}): {type(error).__name__}", file=sys.stderr)
            time.sleep(WAIT_SECONDS)
            continue
        print(f"bucket {settings.s3_bucket_raw} {'created' if created else 'already exists'}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
