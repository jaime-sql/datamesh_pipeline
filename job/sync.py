"""
pg-to-bq-sync: copies bronze.cliente / bronze.pedido / bronze.detalle_pedido
from Neon Postgres into the pg_bronze_replica BigQuery dataset.

Design, deliberately kept simple and inspectable:
  - One real, plain SQL file per source table (job/sql/extract_*.sql) — no
    query-building abstraction. To break this pipeline on purpose later,
    edit one of those .sql files (or drop/rename a source column) and
    redeploy, or revoke a permission from the service account / DB role.
  - Full snapshot per run (read everything, BigQuery WRITE_TRUNCATE). No
    incremental/CDC logic, since the source has no change-tracking columns
    and the data volume is tiny.
  - Any failure (bad query, connection error, permission error, BigQuery
    load error) raises and the process exits non-zero, so the Cloud Run Job
    execution is marked Failed — visible to Cloud Monitoring / a downstream
    incident-response tool.

Required environment variables:
  PG_CONNECTION_STRING  - Postgres connection string (read-only role)
  BQ_PROJECT            - GCP project id, e.g. dataengineering-505822
  BQ_DATASET            - BigQuery dataset id, e.g. pg_bronze_replica
"""

import datetime as dt
import decimal
import os
import pathlib
import sys

import psycopg2
import psycopg2.extras
from google.cloud import bigquery

SQL_DIR = pathlib.Path(__file__).parent / "sql"

# table name -> sql filename
TABLES = {
    "cliente": "extract_cliente.sql",
    "pedido": "extract_pedido.sql",
    "detalle_pedido": "extract_detalle_pedido.sql",
}


def json_safe(value):
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def extract_table(pg_conn, table: str) -> list[dict]:
    sql_path = SQL_DIR / TABLES[table]
    query = sql_path.read_text(encoding="utf-8")

    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()

    synced_at = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for row in rows:
        record = {k: json_safe(v) for k, v in row.items()}
        record["_synced_at"] = synced_at
        out.append(record)
    return out


def load_table(bq_client: bigquery.Client, dataset: str, table: str, rows: list[dict]) -> int:
    table_ref = f"{bq_client.project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq_client.load_table_from_json(rows, table_ref, job_config=job_config)
    job.result()  # raises on failure
    return job.output_rows


def main() -> int:
    pg_conn_str = os.environ["PG_CONNECTION_STRING"]
    bq_project = os.environ["BQ_PROJECT"]
    bq_dataset = os.environ["BQ_DATASET"]

    print(f"Connecting to source Postgres...")
    pg_conn = psycopg2.connect(pg_conn_str, connect_timeout=15)
    bq_client = bigquery.Client(project=bq_project)

    total_rows = 0
    try:
        for table in TABLES:
            print(f"Extracting bronze.{table} ...")
            rows = extract_table(pg_conn, table)
            print(f"  {len(rows)} rows extracted from bronze.{table}")

            loaded = load_table(bq_client, bq_dataset, table, rows)
            print(f"  {loaded} rows loaded into {bq_project}.{bq_dataset}.{table}")
            total_rows += loaded
    finally:
        pg_conn.close()

    print(f"Sync complete: {total_rows} total rows across {len(TABLES)} tables.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SYNC FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
