"""
Creates (or resets) a dedicated least-privilege, read-only Postgres role on
Neon (`pg_to_bq_readonly`), scoped to SELECT on the `bronze` schema only,
then pushes the resulting connection string straight into the
`neon-readonly-connection-string` Secret Manager secret via `gcloud`.

The generated password/connection string is never printed to stdout, never
written to a file, and is piped directly into `gcloud secrets versions add`
via stdin.

Requires NEON_DATABASE_URL (admin/owner credentials) in .env, and `gcloud`
authenticated with access to the target project.

Usage:
    python scripts/create_readonly_role.py
"""

import os
import secrets
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit, quote

from dotenv import load_dotenv
import psycopg2

load_dotenv()

ROLE_NAME = "bq_sync_readonly"  # NB: Postgres reserves role names starting with "pg_"
SCHEMA = "bronze"
SECRET_NAME = "neon-readonly-connection-string"
GCP_PROJECT = "dataengineering-505822"

DDL_STATEMENTS = [
    # CREATE ROLE / ALTER ROLE can't easily be templated with %s for identifiers,
    # so we validate ROLE_NAME above is a fixed constant (no user input) and
    # inline it safely.
    "SELECT 1 FROM pg_roles WHERE rolname = %s",
]


def build_readonly_url(admin_url: str, password: str) -> str:
    parts = urlsplit(admin_url)
    netloc = f"{ROLE_NAME}:{quote(password)}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def main() -> int:
    admin_url = os.environ.get("NEON_DATABASE_URL")
    if not admin_url:
        print("NEON_DATABASE_URL not set in .env", file=sys.stderr)
        return 1

    password = secrets.token_urlsafe(24)

    conn = psycopg2.connect(admin_url, connect_timeout=10)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,))
            exists = cur.fetchone() is not None

            if exists:
                cur.execute(f'ALTER ROLE "{ROLE_NAME}" WITH LOGIN PASSWORD %s', (password,))
                print(f"Role {ROLE_NAME} already existed; password rotated.")
            else:
                cur.execute(f'CREATE ROLE "{ROLE_NAME}" WITH LOGIN PASSWORD %s', (password,))
                print(f"Role {ROLE_NAME} created.")

            cur.execute(f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO "{ROLE_NAME}"')
            cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{SCHEMA}" TO "{ROLE_NAME}"')
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{SCHEMA}" GRANT SELECT ON TABLES TO "{ROLE_NAME}"'
            )
            print(f"Granted USAGE + SELECT on schema '{SCHEMA}' (incl. future tables) to {ROLE_NAME}.")
    finally:
        conn.close()

    readonly_url = build_readonly_url(admin_url, password)

    gcloud_cmd = "gcloud.cmd" if os.name == "nt" else "gcloud"
    result = subprocess.run(
        [
            gcloud_cmd, "secrets", "versions", "add", SECRET_NAME,
            "--data-file=-",
            f"--project={GCP_PROJECT}",
        ],
        input=readonly_url.encode("utf-8"),
        capture_output=True,
    )
    print(result.stdout.decode(errors="replace"))
    if result.returncode != 0:
        print(result.stderr.decode(errors="replace"), file=sys.stderr)
        return result.returncode

    print(f"New connection string stored as a version of secret '{SECRET_NAME}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
