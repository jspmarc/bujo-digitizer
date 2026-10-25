import os
import tempfile
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytest

# Importing bujo_digitizer builds the app, which resolves Settings eagerly and runs
# migrations. Keep the suite hermetic instead of relying on a developer's .env file
# (or writing a db into the working directory), and put these env vars in place
# before the package import below.
os.environ.setdefault("SQLITE_PATH", str(Path(tempfile.mkdtemp()) / "test.sqlite3"))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://openai.test/v1")
os.environ.setdefault("PAPERLESS_BASE_URL", "http://paperless.test")
os.environ.setdefault("PAPERLESS_TOKEN", "test-token")
os.environ.setdefault("PAPERLESS_DIGITIZED_TAG_ID", "6")

from bujo_digitizer.config import Settings

# pydantic-settings still reads unset fields from a developer .env file; only the
# environment variables above should configure the test suite.
Settings.model_config["env_file"] = None


@pytest.fixture
def anyio_backend() -> str:
	return "asyncio"


@pytest.fixture
def pdf_bytes() -> bytes:
	"""A tiny two-page PDF used wherever rasterization is needed."""
	pdf = pdfium.PdfDocument.new()
	pdf.new_page(200, 200)
	pdf.new_page(200, 200)
	buffer = BytesIO()
	pdf.save(buffer)
	pdf.close()
	return buffer.getvalue()
