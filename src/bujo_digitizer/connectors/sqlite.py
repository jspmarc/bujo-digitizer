import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from bujo_digitizer.database import migrate


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

	def initialize(self) -> None:
		migrate(self._db_path)
