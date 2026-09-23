import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import TypedDict

_CREATE_RESULT_TABLE = """
CREATE TABLE IF NOT EXISTS to_review_digitize_result (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	paperless_doc_id INTEGER NOT NULL,
	doc_title TEXT NOT NULL,
	parse_result TEXT,
	bbox_elements TEXT NOT NULL
)
"""

_CREATE_PAGE_TABLE = """
CREATE TABLE IF NOT EXISTS to_review_digitize_page (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	result_id INTEGER NOT NULL,
	page_index INTEGER NOT NULL,
	image BLOB NOT NULL
)
"""

_CREATE_JOB_TABLE = """
CREATE TABLE IF NOT EXISTS digitize_job (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	paperless_doc_id INTEGER NOT NULL,
	doc_title TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'pending',
	attempts INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3,
	last_error TEXT,
	created_at TEXT NOT NULL DEFAULT (datetime('now')),
	updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Paperless may deliver the same webhook twice, so a document can only have one job queued at a time.
_CREATE_JOB_ACTIVE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS digitize_job_active_doc ON digitize_job (paperless_doc_id)
	WHERE status IN ('pending', 'running')
"""

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
#: Statuses still worth surfacing in the UI: queued, running, or out of retries.
JOB_STATUSES_ATTENTION = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_FAILED)


class DigitizeResultRow(TypedDict):
	id: int
	paperless_doc_id: int
	doc_title: str
	parse_result: str | None
	bbox_elements: str


class DigitizeJobRow(TypedDict):
	id: int
	paperless_doc_id: int
	doc_title: str
	status: str
	attempts: int
	max_attempts: int
	last_error: str | None
	created_at: str
	updated_at: str


def _to_row(row: sqlite3.Row) -> DigitizeResultRow:
	return DigitizeResultRow(
		id=row["id"],
		paperless_doc_id=row["paperless_doc_id"],
		doc_title=row["doc_title"],
		parse_result=row["parse_result"],
		bbox_elements=row["bbox_elements"],
	)


def _to_job_row(row: sqlite3.Row) -> DigitizeJobRow:
	return DigitizeJobRow(
		id=row["id"],
		paperless_doc_id=row["paperless_doc_id"],
		doc_title=row["doc_title"],
		status=row["status"],
		attempts=row["attempts"],
		max_attempts=row["max_attempts"],
		last_error=row["last_error"],
		created_at=row["created_at"],
		updated_at=row["updated_at"],
	)


class SqliteStore:
	"""Shared connection handling for stores backed by the same SQLite file."""

	def __init__(self, db_path: str):
		self._db_path = db_path

	@contextmanager
	def _connect(self) -> Generator[sqlite3.Connection]:
		conn = sqlite3.connect(self._db_path)
		conn.row_factory = sqlite3.Row
		# The request handlers and the background worker write concurrently, so let them
		# share the file (WAL) and wait briefly instead of failing on a locked database.
		conn.execute("PRAGMA journal_mode=WAL")
		conn.execute("PRAGMA busy_timeout=5000")
		try:
			yield conn
			conn.commit()
		finally:
			conn.close()


class DigitizeResultStore(SqliteStore):
	def initialize(self) -> None:
		with self._connect() as conn:
			conn.execute(_CREATE_RESULT_TABLE)
			conn.execute(_CREATE_PAGE_TABLE)
			columns = {row["name"] for row in conn.execute("PRAGMA table_info(to_review_digitize_result)")}
			if "doc_title" not in columns:
				conn.execute("ALTER TABLE to_review_digitize_result ADD COLUMN doc_title TEXT NOT NULL DEFAULT ''")

	def save(
		self,
		paperless_doc_id: int,
		doc_title: str,
		parse_result: str | None,
		bbox_elements: str,
		pages: Sequence[bytes],
	) -> int:
		with self._connect() as conn:
			cursor = conn.execute(
				"INSERT INTO to_review_digitize_result (paperless_doc_id, doc_title, parse_result, bbox_elements) VALUES (?, ?, ?, ?)",
				(paperless_doc_id, doc_title, parse_result, bbox_elements),
			)
			result_id = cursor.lastrowid
			_ = conn.executemany(
				"INSERT INTO to_review_digitize_page (result_id, page_index, image) VALUES (?, ?, ?)",
				[(result_id, index, bytes(page)) for index, page in enumerate(pages)],
			)
			return int(result_id)

	def list_all(self) -> list[DigitizeResultRow]:
		with self._connect() as conn:
			rows = conn.execute("SELECT * FROM to_review_digitize_result ORDER BY id DESC").fetchall()
			return [_to_row(row) for row in rows]

	def get(self, id: int) -> DigitizeResultRow | None:
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM to_review_digitize_result WHERE id = ?", (id,)).fetchone()
			return _to_row(row) if row is not None else None

	def page_count(self, id: int) -> int:
		with self._connect() as conn:
			row = conn.execute(
				"SELECT COUNT(*) AS count FROM to_review_digitize_page WHERE result_id = ?",
				(id,),
			).fetchone()
			return int(row["count"])

	def get_page(self, id: int, page_index: int) -> bytes | None:
		with self._connect() as conn:
			row = conn.execute(
				"SELECT image FROM to_review_digitize_page WHERE result_id = ? AND page_index = ?",
				(id, page_index),
			).fetchone()
			return bytes(row["image"]) if row is not None else None

	def delete(self, id: int) -> None:
		with self._connect() as conn:
			_ = conn.execute("DELETE FROM to_review_digitize_page WHERE result_id = ?", (id,))
			_ = conn.execute("DELETE FROM to_review_digitize_result WHERE id = ?", (id,))


class DigitizeJobStore(SqliteStore):
	def initialize(self) -> None:
		with self._connect() as conn:
			conn.execute(_CREATE_JOB_TABLE)
			conn.execute(_CREATE_JOB_ACTIVE_INDEX)

	def enqueue(self, paperless_doc_id: int, doc_title: str, max_attempts: int = 3) -> int:
		with self._connect() as conn:
			try:
				cursor = conn.execute(
					"INSERT INTO digitize_job (paperless_doc_id, doc_title, max_attempts) VALUES (?, ?, ?)",
					(paperless_doc_id, doc_title, max_attempts),
				)
				return int(cursor.lastrowid)
			except sqlite3.IntegrityError:
				row = conn.execute(
					"SELECT id FROM digitize_job WHERE paperless_doc_id = ? AND status IN (?, ?)",
					(paperless_doc_id, JOB_STATUS_PENDING, JOB_STATUS_RUNNING),
				).fetchone()
				if row is None:
					raise
				return int(row["id"])

	def claim_next(self) -> DigitizeJobRow | None:
		with self._connect() as conn:
			row = conn.execute(
				"""
				UPDATE digitize_job
				   SET status = ?, attempts = attempts + 1, updated_at = datetime('now')
				 WHERE id = (SELECT id FROM digitize_job WHERE status = ? ORDER BY id LIMIT 1)
				   AND status = ?
				RETURNING *
				""",
				(JOB_STATUS_RUNNING, JOB_STATUS_PENDING, JOB_STATUS_PENDING),
			).fetchone()
			return _to_job_row(row) if row is not None else None

	def complete(self, id: int) -> None:
		with self._connect() as conn:
			_ = conn.execute(
				"UPDATE digitize_job SET status = ?, last_error = NULL, updated_at = datetime('now') WHERE id = ?",
				(JOB_STATUS_DONE, id),
			)

	def fail(self, id: int, error: str) -> None:
		with self._connect() as conn:
			_ = conn.execute(
				"""
				UPDATE digitize_job
				   SET status = CASE WHEN attempts >= max_attempts THEN ? ELSE ? END,
				       last_error = ?, updated_at = datetime('now')
				 WHERE id = ? AND status = ?
				""",
				(JOB_STATUS_FAILED, JOB_STATUS_PENDING, error, id, JOB_STATUS_RUNNING),
			)

	def requeue_running(self) -> int:
		with self._connect() as conn:
			cursor = conn.execute(
				"UPDATE digitize_job SET status = ?, updated_at = datetime('now') WHERE status = ?",
				(JOB_STATUS_PENDING, JOB_STATUS_RUNNING),
			)
			return int(cursor.rowcount)

	def get(self, id: int) -> DigitizeJobRow | None:
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM digitize_job WHERE id = ?", (id,)).fetchone()
			return _to_job_row(row) if row is not None else None

	def retry(self, id: int) -> bool:
		with self._connect() as conn:
			cursor = conn.execute(
				"""
				UPDATE digitize_job
				   SET status = ?, attempts = 0, last_error = NULL, updated_at = datetime('now')
				 WHERE id = ? AND status = ?
				""",
				(JOB_STATUS_PENDING, id, JOB_STATUS_FAILED),
			)
			return cursor.rowcount > 0

	def delete(self, id: int) -> bool:
		with self._connect() as conn:
			cursor = conn.execute("DELETE FROM digitize_job WHERE id = ?", (id,))
			return cursor.rowcount > 0

	def list_jobs(self, statuses: Sequence[str] = JOB_STATUSES_ATTENTION) -> list[DigitizeJobRow]:
		with self._connect() as conn:
			placeholders = ", ".join("?" * len(statuses))
			rows = conn.execute(
				f"SELECT * FROM digitize_job WHERE status IN ({placeholders}) ORDER BY id DESC",
				tuple(statuses),
			).fetchall()
			return [_to_job_row(row) for row in rows]
