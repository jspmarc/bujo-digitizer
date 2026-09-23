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


class DigitizeResultRow(TypedDict):
	id: int
	paperless_doc_id: int
	doc_title: str
	parse_result: str | None
	bbox_elements: str


def _to_row(row: sqlite3.Row) -> DigitizeResultRow:
	return DigitizeResultRow(
		id=row["id"],
		paperless_doc_id=row["paperless_doc_id"],
		doc_title=row["doc_title"],
		parse_result=row["parse_result"],
		bbox_elements=row["bbox_elements"],
	)


class DigitizeResultStore:
	def __init__(self, db_path: str):
		self._db_path = db_path

	@contextmanager
	def _connect(self) -> Generator[sqlite3.Connection]:
		conn = sqlite3.connect(self._db_path)
		conn.row_factory = sqlite3.Row
		try:
			yield conn
			conn.commit()
		finally:
			conn.close()

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
			conn.executemany(
				"INSERT INTO to_review_digitize_page (result_id, page_index, image) VALUES (?, ?, ?)",
				[(result_id, index, bytes(page)) for index, page in enumerate(pages)],
			)
			return result_id

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
				"SELECT COUNT(*) AS count FROM to_review_digitize_page WHERE result_id = ?", (id,)
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
			conn.execute("DELETE FROM to_review_digitize_page WHERE result_id = ?", (id,))
			conn.execute("DELETE FROM to_review_digitize_result WHERE id = ?", (id,))
