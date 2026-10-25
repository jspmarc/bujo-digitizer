from pathlib import Path

from yoyo import get_backend, read_migrations

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migrate(db_path: str) -> None:
	"""Apply all pending SQL migrations to the SQLite database."""
	migrations = read_migrations(str(MIGRATIONS_DIR))
	with get_backend(f"sqlite:///{Path(db_path).resolve()}") as backend, backend.lock():
		_ = backend.apply_migrations(backend.to_apply(migrations))
