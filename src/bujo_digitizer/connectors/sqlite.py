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
		# Set the wait first: switching journal modes takes an exclusive lock, and the
		# request handlers and the background worker write to the same file.
		conn.execute("PRAGMA busy_timeout=5000")
		try:
			yield conn
			conn.commit()
		finally:
			conn.close()

	def initialize(self) -> None:
		migrate(self._db_path)
		# WAL is persistent in the database file, so enable it once after migrating
		# instead of racing the delete->wal transition on every new connection.
		with self._connect() as conn:
			_ = conn.execute("PRAGMA journal_mode=WAL")
