# datamesh_pipeline

A small, serverless ELT pipeline: copies customer/order data from Postgres
(Neon) into BigQuery on a schedule, using a Cloud Run Job triggered by Cloud
Scheduler. No Composer, no Datastream — just a Python script in a container.

This pipeline is intentionally simple and will later be used as a target for
deliberately-injected failures (bad query, dropped/renamed column, bad
credentials, slow query) to test a separate monitoring/incident-response
tool end-to-end. Because of that, every resource created below is documented
with its real name/ID, and the core copy logic is three plain, readable
`.sql` files — not hidden behind an ORM or query-builder.

## Status: Phase 1 complete — pipeline built, deployed, and verified end-to-end

Confirmed working: Cloud Scheduler → Cloud Run Job → Neon (read-only) →
BigQuery, running on an hourly schedule.

## GCP project

| | |
|---|---|
| Project ID | `dataengineering-505822` |
| Project number | `73111084697` |
| Region | `us-central1` |
| Shared with | DataMesh Warden (separate, unrelated project in the same GCP project — a `warden-api-run` service account exists there but nothing in this pipeline touches it) |

## Source: Postgres (Neon)

Neon was chosen over Supabase — Supabase's project had no application data
(only default `auth`/`storage`/`realtime`/`vault` system schemas). Neon had a
pre-existing `bronze` schema with real (if tiny) customer/order data, which
was extended with a few more seed rows so the pipeline has something
meaningful to copy.

| | |
|---|---|
| Provider | Neon |
| Host | `ep-dawn-pond-axylpitj-pooler.c-4.us-east-2.aws.neon.tech` |
| Database | `neondb` |
| Schema read by the pipeline | `bronze` |
| **Pipeline's DB role** | `bq_sync_readonly` — `LOGIN` + `USAGE` on schema `bronze` + `SELECT` on all current and future tables in `bronze`. Cannot `INSERT`/`UPDATE`/`DELETE`/DDL (verified). This is what's stored in Secret Manager and used by the Cloud Run Job — **not** the admin/owner credentials. |
| Admin/owner credentials | Kept locally only, in `.env` (git-ignored), as `NEON_DATABASE_URL`. Used only for one-off admin scripts (seeding, role management). Never deployed anywhere. |

### Source tables (`bronze` schema, no PK/FK constraints — raw landing zone style)

**`bronze.cliente`** (customers) — 7 rows

| column | type |
|---|---|
| dui_cliente | varchar (natural identifier, Salvadoran national ID format) |
| nombre | varchar |
| telefono | varchar |
| direccion | varchar |
| id_municipio | integer |

**`bronze.pedido`** (order headers) — 8 rows. This table did not exist
originally; it was added (via `scripts/seed_bronze.py`) so that
`detalle_pedido` rows (which reference `id_pedido`) have an actual
order/customer link.

| column | type |
|---|---|
| id_pedido | integer |
| dui_cliente | varchar |
| fecha_pedido | date |
| estado | varchar (`completado` / `pendiente` / `cancelado`) |

**`bronze.detalle_pedido`** (order line items) — 13 rows (4 pre-existing + 9 seeded)

| column | type |
|---|---|
| id_detalle | integer |
| id_pedido | integer |
| id_producto | varchar |
| cantidad | integer |
| precio_unitario_historico | numeric |

## Target: BigQuery

| | |
|---|---|
| Dataset | `pg_bronze_replica` |
| Location | `us-central1` |
| Tables | `cliente`, `pedido`, `detalle_pedido` — 1:1 mirror of source columns, plus a `_synced_at TIMESTAMP` column added by the loader |
| Load strategy | Full snapshot refresh (`WRITE_TRUNCATE`) every run — source has no updated_at/change-tracking columns, and data volume is tiny, so incremental logic isn't warranted |
| Full table paths | `dataengineering-505822.pg_bronze_replica.cliente`, `.pedido`, `.detalle_pedido` |

## GCP resources created

| Resource | Name / ID | Notes |
|---|---|---|
| Artifact Registry repo (Docker) | `datamesh-pipeline` (`us-central1`) | Holds the sync job image |
| Container image | `us-central1-docker.pkg.dev/dataengineering-505822/datamesh-pipeline/pg-to-bq-sync:latest` | Built via `gcloud builds submit` from `job/` |
| Secret Manager secret | `neon-readonly-connection-string` | Holds the `bq_sync_readonly` connection string. Mounted into the job as the `PG_CONNECTION_STRING` env var (never baked into the image) |
| Service account (job runtime) | `pg-to-bq-sync-runner@dataengineering-505822.iam.gserviceaccount.com` | Roles: BigQuery Data Editor scoped to the `pg_bronze_replica` **dataset only** (dataset ACL, not project IAM) + `roles/bigquery.jobUser` (project-level; required by BigQuery to run jobs, no dataset-scoped equivalent) + `roles/secretmanager.secretAccessor` scoped to the one secret |
| Service account (scheduler invoker) | `pg-to-bq-sync-invoker@dataengineering-505822.iam.gserviceaccount.com` | Role: `roles/run.invoker`, scoped to just the `pg-to-bq-sync` job |
| Cloud Run Job | `pg-to-bq-sync` (`us-central1`) | 1 vCPU / 512Mi, `max-retries=1`, `task-timeout=300s`. Scale-to-zero — no cost while idle |
| Cloud Scheduler job | `pg-to-bq-sync-trigger` (`us-central1`) | Cron `0 * * * *` (hourly, UTC). Calls the Cloud Run Admin API v2 `jobs.run` endpoint (`https://run.googleapis.com/v2/projects/dataengineering-505822/locations/us-central1/jobs/pg-to-bq-sync:run`) using an OAuth token signed by the invoker service account |

### Actual cost so far / going forward

Everything fits inside GCP's always-free monthly tier at this data volume
and an hourly schedule (~720 runs/month, each finishing in seconds of actual
container run time): Artifact Registry storage, Secret Manager
access/versions, Cloud Run Job vCPU/memory-seconds, the 1 Cloud Scheduler
job (3 free/month), and BigQuery storage/query volume are all well under
their respective free-tier limits. **Effectively $0/month.**

## How it works (`job/`)

- `job/sql/extract_cliente.sql`, `extract_pedido.sql`, `extract_detalle_pedido.sql`
  — plain `SELECT ... FROM bronze.X` queries, one per table. No abstraction:
  edit one of these directly (or rename/drop a source column, or revoke a
  grant) to intentionally break a specific part of the pipeline later.
- `job/sync.py` — for each table: runs its `.sql` file against Neon, adds a
  `_synced_at` timestamp, and loads the rows into BigQuery with
  `WRITE_TRUNCATE`. Any failure (bad query, connection error, permission
  error, BigQuery load error) makes the process exit non-zero, so the Cloud
  Run Job execution is marked **Failed** — visible in Cloud Logging /
  Cloud Monitoring and to any downstream incident-response tool.
- `job/Dockerfile` — `python:3.12-slim` base, installs `job/requirements.txt`,
  entrypoint `python sync.py`.

### Manually triggering a run

```powershell
gcloud run jobs execute pg-to-bq-sync --region=us-central1 --project=dataengineering-505822 --wait
```

### Viewing logs for a specific execution

```powershell
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=pg-to-bq-sync' --project=dataengineering-505822 --limit=50 --order=desc
```

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # then fill in real values (admin Neon URL), never commit .env
```

- `scripts/probe_sources.py [schema]` — read-only check of table/column/row-count
  metadata for whichever of `NEON_DATABASE_URL` / `SUPABASE_DATABASE_URL` are set.
  Never prints connection strings or row data.
- `scripts/seed_bronze.py` — idempotent seed of `bronze.cliente` / `bronze.pedido` /
  `bronze.detalle_pedido` on Neon. Safe to re-run.
- `scripts/create_readonly_role.py` — (re)creates the `bq_sync_readonly` Postgres
  role and rotates its password directly into the `neon-readonly-connection-string`
  secret. The password is never printed or written to disk.
- `scripts/verify_readonly_secret.py` — fetches the secret in-memory and confirms
  it can `SELECT` but not `INSERT` against `bronze.*`.

## Handoff notes (for future monitoring/incident-response integration)

Everything an external monitoring tool would need to watch or an
incident-response drill would need to target:

- **Cloud Run Job**: `pg-to-bq-sync` in `us-central1`, project `dataengineering-505822`
- **Cloud Scheduler job**: `pg-to-bq-sync-trigger` in `us-central1`, hourly (`0 * * * *` UTC)
- **BigQuery dataset/tables**: `dataengineering-505822.pg_bronze_replica.{cliente,pedido,detalle_pedido}`
- **Source**: Neon Postgres, `bronze` schema, role `bq_sync_readonly`, connection string in Secret Manager secret `neon-readonly-connection-string`
- **Service accounts**: `pg-to-bq-sync-runner@...` (job runtime), `pg-to-bq-sync-invoker@...` (scheduler)
- **Failure signal**: any exception in `job/sync.py` → non-zero exit → Cloud Run Job execution status `Failed`, visible via `gcloud run jobs executions list --job=pg-to-bq-sync` or Cloud Logging/Monitoring

Ideas for later intentional-failure testing (per the original ask): edit an
`extract_*.sql` file to reference a dropped/renamed column and redeploy;
revoke `SELECT` from `bq_sync_readonly` on one table; expire/rotate the
Neon password without updating the secret; or point `BQ_DATASET` at a
nonexistent dataset.
