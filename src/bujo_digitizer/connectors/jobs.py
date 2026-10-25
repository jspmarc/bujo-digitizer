import sqlite3
from collections.abc import Sequence
from typing import TypedDict

from bujo_digitizer.connectors.sqlite import SqliteStore

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
#: Statuses still worth surfacing in the UI: queued, running, or out of retries.
JOB_STATUSES_ATTENTION = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_FAILED)


class DigitizeJobRow(TypedDict):
	id: int
	paperless_doc_id: int
	doc_title: str
	doc_created: str
	status: str
	attempts: int
	max_attempts: int
	last_error: str | None
	created_at: str
	updated_at: str


def _to_job_row(row: sqlite3.Row) -> DigitizeJobRow:
	return DigitizeJobRow(
		id=row["id"],
		paperless_doc_id=row["paperless_doc_id"],
		doc_title=row["doc_title"],
		doc_created=row["doc_created"],
		status=row["status"],
		attempts=row["attempts"],
		max_attempts=row["max_attempts"],
		last_error=row["last_error"],
		created_at=row["created_at"],
		updated_at=row["updated_at"],
	)


class DigitizeJobStore(SqliteStore):
	def enqueue(self, paperless_doc_id: int, doc_title: str, doc_created: str, max_attempts: int = 3) -> int:
		with self._connect() as conn:
			try:
				cursor = conn.execute(
					"INSERT INTO digitize_job (paperless_doc_id, doc_title, doc_created, max_attempts) VALUES (?, ?, ?, ?)",
					(paperless_doc_id, doc_title, doc_created, max_attempts),
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

	def retry_failed(self) -> int:
		with self._connect() as conn:
			cursor = conn.execute(
				"UPDATE digitize_job SET status = ?, last_error = NULL, updated_at = datetime('now') WHERE status = ?",
				(JOB_STATUS_PENDING, JOB_STATUS_FAILED),
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
