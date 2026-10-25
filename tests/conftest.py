import os
from io import BytesIO

import pypdfium2 as pdfium
import pytest

from bujo_digitizer.config import Settings

# Settings is required at import time by the logger/controllers. Keep the suite hermetic
# instead of relying on a developer's .env file.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://openai.test/v1")
os.environ.setdefault("PAPERLESS_BASE_URL", "http://paperless.test")
os.environ.setdefault("PAPERLESS_TOKEN", "test-token")

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
