import sqlite3
from collections.abc import Sequence
from typing import TypedDict

from bujo_digitizer.connectors.sqlite import SqliteStore


class DigitizeResultRow(TypedDict):
	id: int
	paperless_doc_id: int
	doc_title: str
	doc_created: str
	parse_result: str | None
	bbox_elements: str


def _to_row(row: sqlite3.Row) -> DigitizeResultRow:
	return DigitizeResultRow(
		id=row["id"],
		paperless_doc_id=row["paperless_doc_id"],
		doc_title=row["doc_title"],
		doc_created=row["doc_created"],
		parse_result=row["parse_result"],
		bbox_elements=row["bbox_elements"],
	)


class DigitizeResultStore(SqliteStore):
	def save(
		self,
		paperless_doc_id: int,
		doc_title: str,
		doc_created: str,
		parse_result: str | None,
		bbox_elements: str,
		pages: Sequence[bytes],
	) -> int:
		with self._connect() as conn:
			cursor = conn.execute(
				"INSERT INTO to_review_digitize_result (paperless_doc_id, doc_title, doc_created, parse_result, bbox_elements) VALUES (?, ?, ?, ?, ?)",
				(paperless_doc_id, doc_title, doc_created, parse_result, bbox_elements),
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
