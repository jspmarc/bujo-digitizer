import sqlite3
from contextlib import closing

from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.database import MIGRATIONS_DIR, migrate

_MIGRATION_IDS = {path.stem for path in MIGRATIONS_DIR.glob("*.sql")}


def _applied_ids(path: str) -> set[str]:
	with closing(sqlite3.connect(path)) as conn:
		exists = conn.execute(
			"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '_yoyo_migration'"
		).fetchone()
		if exists is None:
			return set()
		return {row[0] for row in conn.execute("SELECT migration_id FROM _yoyo_migration")}


def _columns(path: str, table: str) -> set[str]:
	with closing(sqlite3.connect(path)) as conn:
		return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _execute(path: str, script: str) -> None:
	with closing(sqlite3.connect(path)) as conn:
		conn.executescript(script)
		conn.commit()


def test_initialize_applies_every_bundled_migration(tmp_path) -> None:
	path = str(tmp_path / "results.sqlite3")
	store = DigitizeResultStore(path)

	store.initialize()

	assert _applied_ids(path) == _MIGRATION_IDS
	assert {"doc_title", "doc_created"} <= _columns(path, "to_review_digitize_result")


def test_initialize_is_idempotent_and_preserves_data(tmp_path) -> None:
	path = str(tmp_path / "results.sqlite3")
	store = DigitizeResultStore(path)
	store.initialize()
	result_id = store.save(7, "Doc", "2026-01-05", None, "[]", [])

	store.initialize()

	assert _applied_ids(path) == _MIGRATION_IDS
	assert store.get(result_id)["doc_title"] == "Doc"


def test_existing_database_is_adopted_without_data_loss(tmp_path) -> None:
	path = str(tmp_path / "existing.sqlite3")
	_execute(
		path,
		"""
		CREATE TABLE to_review_digitize_result (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			paperless_doc_id INTEGER NOT NULL,
			doc_title TEXT NOT NULL,
			doc_created TEXT NOT NULL DEFAULT '',
			parse_result TEXT,
			bbox_elements TEXT NOT NULL
		);
		CREATE TABLE to_review_digitize_page (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			result_id INTEGER NOT NULL,
			page_index INTEGER NOT NULL,
			image BLOB NOT NULL
		);
		INSERT INTO to_review_digitize_result (paperless_doc_id, doc_title, doc_created, parse_result, bbox_elements)
			VALUES (7, 'Existing', '2026-01-05', '[]', '<div></div>');
		""",
	)

	store = DigitizeResultStore(path)
	store.initialize()

	assert _applied_ids(path) == _MIGRATION_IDS
	row = store.get(1)
	assert row is not None
	assert row["doc_title"] == "Existing"
	assert row["doc_created"] == "2026-01-05"


def test_job_store_uses_the_same_migration_set(tmp_path) -> None:
	path = str(tmp_path / "jobs.sqlite3")
	jobs = DigitizeJobStore(path)

	jobs.initialize()

	assert _applied_ids(path) == _MIGRATION_IDS
	job_id = jobs.enqueue(7, "Doc", "2026-01-05")
	assert jobs.get(job_id)["doc_created"] == "2026-01-05"


def test_migrate_is_a_noop_on_an_up_to_date_database(tmp_path) -> None:
	path = str(tmp_path / "results.sqlite3")
	migrate(path)

	migrate(path)

	assert _applied_ids(path) == _MIGRATION_IDS
