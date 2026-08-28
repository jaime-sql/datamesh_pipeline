# Agent working conventions for this repo

## Git

- Default branch is `main`, not `master`.
- Do **not** add `Co-authored-by:` trailers (Cursor, Claude, or any other
  agent/tool) to commits or PRs. Jaime Garcia is the sole author on every
  commit. Do not add any other agent-attribution footer/trailer either.
- Only commit when explicitly asked to.

## Cloud resources (GCP)

- Never create, modify, or delete GCP or database resources without first
  walking the user through what will be created/changed and getting
  explicit confirmation to proceed.
- Use least-privilege credentials/roles wherever possible (dedicated
  read-only DB roles, dataset-scoped IAM instead of project-wide, secrets
  scoped to the one service account that needs them).
- Document every created resource's real name/ID in `README.md` as it's
  created (this pipeline is meant to later be wired up to an external
  monitoring/incident-response tool, so names/IDs need to be easy to find).

## Pipeline design

- Keep the core Postgres extraction logic as plain, inspectable `.sql`
  files (see `job/sql/`) rather than an abstraction/query-builder — it's
  meant to be easy to intentionally break later for failure-testing.
