import atexit
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytest

# Importing bujo_digitizer builds the app, which resolves Settings eagerly and runs
# migrations. Pin the test database and ignore the developer's .env file before any
# test module imports the package.
test_dir = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, test_dir, ignore_errors=True)
os.environ["SQLITE_PATH"] = str(test_dir / "test.sqlite3")
os.environ["BUJO_ENV_FILE"] = os.devnull
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://openai.test/v1")
os.environ.setdefault("PAPERLESS_BASE_URL", "http://paperless.test")
os.environ.setdefault("PAPERLESS_TOKEN", "test-token")
os.environ.setdefault("PAPERLESS_DIGITIZED_TAG_ID", "6")


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
