from pathlib import Path
from urllib.parse import quote

from yoyo import get_backend, read_migrations

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migrate(db_path: str) -> None:
	"""Apply all pending SQL and Python migrations to the SQLite database."""
	migrations = read_migrations(str(MIGRATIONS_DIR))
	if db_path == ":memory:":
		# yoyo opens `file:{database}?cache=shared`, so the URL needs a database
		# component; plain `sqlite://` would resolve to a file literally named "None".
		url = "sqlite:///:memory:"
	else:
		resolved = Path(db_path).resolve()
		resolved.parent.mkdir(parents=True, exist_ok=True)
		# Quote so paths with spaces or `?`/`#` survive URL parsing.
		url = f"sqlite:///{quote(str(resolved))}"
	with get_backend(url) as backend, backend.lock():
		_ = backend.apply_migrations(backend.to_apply(migrations))
