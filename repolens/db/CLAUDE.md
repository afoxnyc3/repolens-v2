# repolens/db — agent brief

SQLite schema, migration ladder, and data-access layer. Every table
access in the project goes through this package.

## Hard rules

- **No raw SQL outside this package.** All data access lives in
  `repository.py`. If another module needs a new query, add a function
  here and call it.

- **`ORDER BY` fragments are whitelisted.** `list_files(order_by=...)`
  validates against `_ALLOWED_FILE_ORDER`; anything else raises
  `ValueError`. Any future function that interpolates a SQL fragment
  must use the same whitelist pattern.

- **`schema_version` is the migration gate.** `CURRENT_VERSION = 3`
  (see `schema.py`). Fresh DBs are stamped directly to
  `CURRENT_VERSION` after the latest `_CREATE_TABLES` runs; existing
  DBs bridge forward through the `migrations.py` ladder.

- **Migrations are idempotent.** Every `_upgrade_to_vN` function must
  check column existence (via `_has_column` / `PRAGMA table_info`)
  before `ALTER TABLE`. SQLite's `ADD COLUMN` has no `IF NOT EXISTS`
  form. Replaying a migration on an already-upgraded DB must be a
  no-op.

- **Transactions wrap every migration step.** The `migrate()` runner
  applies each version inside `with conn:` so a failing step rolls
  back cleanly and the DB stays at the previous version.

- **`PRAGMA foreign_keys=ON` is required on every connection.** The
  `open_conn` context manager in `connection.py` sets it. Never
  disable — it catches data-integrity bugs.

- **WAL mode is on** (set in `init_db`). `.db-wal` and `.db-shm`
  sidecar files on disk are normal, not leaks.

## Adding a new column / migration

1. Bump `CURRENT_VERSION` in `schema.py`.
2. Update the latest `_CREATE_TABLES` entry so fresh DBs get the new
   shape via `CREATE TABLE IF NOT EXISTS`.
3. Add a `_upgrade_to_vN` function to `migrations.py` that uses
   `_has_column` guards before each `ALTER TABLE`.
4. Register the new version in the `MIGRATIONS` dict.
5. If the new column is user-writable, extend the `allowed` set in
   the corresponding `update_*` function in `repository.py`.
6. Add a test in `tests/test_db_migrations.py` covering both the
   fresh-install path and the v(N-1)→vN upgrade path, plus an
   idempotence check (apply twice, assert single version stamp).

## Related

- Schema diagram + rationale: [DESIGN.md §3](../../DESIGN.md).
- SQL injection audit rationale: [ADR-006](../../docs/decisions/ADR-006-model-ids.md)
  is unrelated; the whitelist landed in the hardening pass — see the
  commit message on `repolens/db/repository.py:_ALLOWED_FILE_ORDER`.
- Connection lifecycle: use `open_conn()` from `repolens/db/connection.py`
  instead of `sqlite3.connect` directly.
