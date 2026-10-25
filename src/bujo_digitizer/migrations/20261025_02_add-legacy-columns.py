"""Add columns missing from databases created before the yoyo baseline.

The initial migration only uses ``CREATE TABLE IF NOT EXISTS``, so yoyo adopts a
pre-existing database without touching its stale schema. Upgrading those
databases needs conditional ``ALTER TABLE`` statements, which SQL migrations
cannot express.
"""

from typing import Any

__depends__ = {"20261025_01_I1O49-initial-schema"}

_MISSING_COLUMNS = {
	"to_review_digitize_result": {
		"doc_title": "TEXT NOT NULL DEFAULT ''",
		"doc_created": "TEXT NOT NULL DEFAULT ''",
	},
	"digitize_job": {
		"doc_created": "TEXT NOT NULL DEFAULT ''",
	},
}


def _columns(conn: Any, table: str) -> set[str]:
	return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn: Any) -> None:
	for table, columns in _MISSING_COLUMNS.items():
		existing = _columns(conn, table)
		for name, definition in columns.items():
			if name not in existing:
				_ = conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _keep_columns(conn: Any) -> None:
	# Which columns this migration added depends on the adopted schema, so a
	# rollback cannot tell them apart from columns that held data already.
	# SQLite can drop columns since 3.35, but doing so here would be lossy.
	pass


step(_add_missing_columns, _keep_columns)  # noqa: F821 - `step` is injected by yoyo
