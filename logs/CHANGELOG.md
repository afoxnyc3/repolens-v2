## 2026-04-15T12:31:04.226605+00:00 | T01 → in_progress


## 2026-04-15T12:31:04.511023+00:00 | T01 → done
Scaffold complete. pyproject.toml (fixed build backend from setuptools.backends.legacy to setuptools.build_meta), all package dirs with __init__.py, conftest.py with tmp_db and sample_repo fixtures, test_scaffold.py for importability check, .venv with all deps installed. CLAUDE.md updated with venv activation instructions. T01 validation passing.

## 2026-04-15T12:36:58.499274+00:00 | T02 → in_progress


## 2026-04-15T12:37:58.264496+00:00 | T02 → done
Implemented repolens/db/schema.py with init_db(), all 6 tables with IF NOT EXISTS, 4 indexes, schema_version seeded to 1, WAL mode, FK enforcement. Added get_schema_version() helper. 25 tests in tests/test_db.py covering table creation, idempotency, index existence, schema version, env var path, parent dir creation, column presence, FK cascade.

## 2026-04-15T12:38:37.323047+00:00 | T04 → in_progress


## 2026-04-15T12:39:29.574264+00:00 | T04 → done
Implemented load_gitignore, is_ignored, is_binary, is_oversized in repolens/ingestion/filters.py. 20 tests passing. Uses gitignore-parser for .gitignore support, null-byte binary detection, stat-based size check. Always filters .git/ components.

