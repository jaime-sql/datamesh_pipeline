"""
Read-only probe of candidate Postgres sources (Neon / Supabase).

Prints only non-sensitive metadata: table names, approximate row counts,
and column names/types. Never prints connection strings or row-level data.

Usage:
    python scripts/probe_sources.py [schema]

If `schema` is omitted, defaults to `public`.
"""

import os
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv
import psycopg2

load_dotenv()

SOURCES = {
    "NEON": os.environ.get("NEON_DATABASE_URL"),
    "SUPABASE": os.environ.get("SUPABASE_DATABASE_URL"),
}

SCHEMA = sys.argv[1] if len(sys.argv) > 1 else "public"

LIST_TABLES_SQL = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = %s
    ORDER BY table_name;
"""

COLUMNS_SQL = """
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position;
"""


def redact_target(conn_str: str) -> str:
    try:
        parts = urlsplit(conn_str)
        return f"{parts.hostname}{parts.path}"
    except Exception:
        return "<unparsable>"


def probe(name: str, conn_str: str) -> None:
    print(f"\n=== {name} (schema: {SCHEMA}) ===")
    print(f"target: {redact_target(conn_str)}")

    try:
        conn = psycopg2.connect(conn_str, connect_timeout=10)
    except Exception as exc:
        print(f"  CONNECTION FAILED: {exc}")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(LIST_TABLES_SQL, (SCHEMA,))
            tables = [r[0] for r in cur.fetchall()]

            if not tables:
                print(f"  no tables found in {SCHEMA} schema")
                return

            for table in tables:
                cur.execute(COLUMNS_SQL, (SCHEMA, table))
                cols = cur.fetchall()

                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{SCHEMA}"."{table}";')
                    count = cur.fetchone()[0]
                except Exception as exc:
                    count = f"<error: {exc}>"

                print(f"  table: {table}  (rows: {count})")
                for col_name, data_type, nullable in cols:
                    print(f"    - {col_name}: {data_type} (nullable={nullable})")
    finally:
        conn.close()


def main() -> int:
    any_configured = False
    for name, conn_str in SOURCES.items():
        if not conn_str:
            print(f"\n=== {name} ===\n  (not configured, skipping)")
            continue
        any_configured = True
        probe(name, conn_str)

    if not any_configured:
        print("\nNo NEON_DATABASE_URL or SUPABASE_DATABASE_URL set in .env. Nothing to probe.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
