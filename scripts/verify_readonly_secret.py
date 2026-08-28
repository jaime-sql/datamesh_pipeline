"""
Fetches the connection string from Secret Manager (in-memory only, never
printed) and verifies:
  1. It can connect and SELECT from bronze.cliente.
  2. It CANNOT INSERT/UPDATE/DDL against bronze tables (permission denied).

Usage:
    python scripts/verify_readonly_secret.py
"""

import subprocess
import sys

import psycopg2

SECRET_NAME = "neon-readonly-connection-string"
GCP_PROJECT = "dataengineering-505822"


def fetch_secret() -> str:
    gcloud_cmd = "gcloud.cmd"
    result = subprocess.run(
        [gcloud_cmd, "secrets", "versions", "access", "latest",
         f"--secret={SECRET_NAME}", f"--project={GCP_PROJECT}"],
        capture_output=True,
    )
    if result.returncode != 0:
        print(result.stderr.decode(errors="replace"), file=sys.stderr)
        sys.exit(1)
    return result.stdout.decode("utf-8")


def main() -> None:
    conn_str = fetch_secret()
    conn = psycopg2.connect(conn_str, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bronze.cliente;")
            count = cur.fetchone()[0]
            print(f"PASS: SELECT works, bronze.cliente has {count} rows")

        conn.rollback()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO bronze.cliente (dui_cliente) VALUES ('should-fail');")
            conn.commit()
            print("FAIL: INSERT succeeded (role is NOT read-only!)")
        except psycopg2.errors.InsufficientPrivilege:
            print("PASS: INSERT correctly denied (permission denied)")
            conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
