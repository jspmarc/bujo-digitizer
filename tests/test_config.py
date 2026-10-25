import pytest
from pydantic import ValidationError

from bujo_digitizer.config import Settings


@pytest.mark.parametrize(
	("overrides", "message"),
	[
		({"WORKER_CONCURRENCY": "0"}, "WORKER_CONCURRENCY"),
		({"JOB_MAX_ATTEMPTS": "0"}, "JOB_MAX_ATTEMPTS"),
		({"WORKER_POLL_SECONDS": "0"}, "WORKER_POLL_SECONDS"),
		({"WORKER_RETRY_INTERVAL_SECONDS": "0"}, "WORKER_RETRY_INTERVAL_SECONDS"),
		({"SQLITE_PATH": ""}, "SQLITE_PATH"),
		({"SQLITE_PATH": ":memory:"}, "in-memory"),
	],
)
def test_settings_reject_invalid_values(overrides: dict[str, str], message: str) -> None:
	with pytest.raises(ValidationError, match=message):
		_ = Settings(**overrides)


def test_settings_accepts_a_file_backed_database() -> None:
	settings = Settings(SQLITE_PATH="/tmp/test.sqlite3", WORKER_CONCURRENCY=4, JOB_MAX_ATTEMPTS=2)

	assert settings.sqlite_path == "/tmp/test.sqlite3"
	assert settings.worker_concurrency == 4
	assert settings.job_max_attempts == 2
