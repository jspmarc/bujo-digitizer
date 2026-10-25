import os
import subprocess
import sys
from pathlib import Path

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


def test_package_import_ignores_a_poisoned_dotenv(tmp_path: Path) -> None:
	_ = (tmp_path / ".env").write_text("OCR_TEMPERATURE=99\n")
	environment = {**os.environ, "BUJO_ENV_FILE": os.devnull}

	completed = subprocess.run(
		[sys.executable, "-c", "import bujo_digitizer"],
		cwd=tmp_path,
		env=environment,
		capture_output=True,
		text=True,
		check=False,
	)

	assert completed.returncode == 0, completed.stderr
