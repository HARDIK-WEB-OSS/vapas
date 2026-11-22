import argparse
import json
import re
import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx

from vapas.jobs.detection import today_ist
from vapas.privacy.notices import CURRENT_NOTICE_VERSION
from vapas.security.private_path_guard import ensure_outside_code_root
from vapas.synthetic.generator import STYLES, generate, render_pdf

PASSWORD = "load-test-river-lantern-42"
TOKEN_IN_LINK = re.compile(r"#token=(\S+)")
STATEMENT_ROWS = 400
STATEMENT_DAYS_BACK = 420
OUTBOX_WAIT_SECONDS = 15.0


def write_statements(out_dir: Path) -> list[str]:
    start = today_ist() - timedelta(days=STATEMENT_DAYS_BACK)
    names = []
    for seed, bank in enumerate(sorted(STYLES)):
        path = out_dir / f"statement-{bank.lower()}.pdf"
        path.write_bytes(render_pdf(generate(bank, 9000 + seed, STATEMENT_ROWS, start)))
        names.append(path.name)
    return names


def verification_token(outbox: Path, email: str) -> str:
    deadline = time.monotonic() + OUTBOX_WAIT_SECONDS
    while time.monotonic() < deadline:
        for path in sorted(outbox.glob("*.json"), reverse=True):
            mail = json.loads(path.read_text(encoding="utf-8"))
            match = TOKEN_IN_LINK.search(mail["body"])
            if mail["to"] == email and mail["kind"] == "verify_email" and match:
                return match.group(1)
        time.sleep(0.2)
    raise TimeoutError(f"no verification email for {email}")


def seed_user(api: httpx.Client, outbox: Path, ip_header: str, index: int, run: str) -> str:
    email = f"load-{run}-{index:05d}@example.in"
    headers = {ip_header: f"10.{index // 65536 % 256}.{index // 256 % 256}.{index % 256}"}
    body = {"email": email, "password": PASSWORD, "consent_notice_version": CURRENT_NOTICE_VERSION}
    api.post("/auth/signup", json=body, headers=headers).raise_for_status()
    token = verification_token(outbox, email)
    api.post("/auth/verify-email", json={"token": token}, headers=headers).raise_for_status()
    return email


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--users", type=int, default=300)
    parser.add_argument("--ip-header", default="X-Load-Client-IP")
    args = parser.parse_args()
    out_dir = ensure_outside_code_root(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    statements = write_statements(out_dir)
    run = time.strftime("%Y%m%d%H%M%S")
    with httpx.Client(base_url=args.api, timeout=30.0) as api:
        emails = [seed_user(api, args.outbox, args.ip_header, index, run) for index in range(args.users)]
    manifest = {"password": PASSWORD, "emails": emails, "statements": statements, "ip_header": args.ip_header}
    (out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    print(f"seeded {len(emails)} users and {len(statements)} statements into {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
