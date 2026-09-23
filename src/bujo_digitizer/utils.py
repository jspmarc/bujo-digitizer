from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO

import pypdfium2 as pdfium

RASTER_MIME_TYPE = "image/jpeg"
MAX_BYTES = 15 * 1024 * 1024  # 15 MB
RENDER_DPI = 200
MAX_IMAGE_DIMENSION = 2400


@dataclass(frozen=True)
class DocumentPage:
	image: bytes
	data_url: str


def to_data_url(content: bytes, mime: str) -> str:
	return f"data:{mime};base64,{b64encode(content).decode('ascii')}"


def rasterize_pdf(content: bytes, dpi: int = RENDER_DPI) -> list[bytes]:
	pages: list[bytes] = []
	pdf = pdfium.PdfDocument(content)
	try:
		for page in pdf:
			image = page.render(scale=dpi / 72).to_pil().convert("RGB")
			image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
			buffer = BytesIO()
			image.save(buffer, format="JPEG", quality=85)
			pages.append(buffer.getvalue())
	finally:
		pdf.close()
	return pages


def to_pages(content: bytes) -> list[DocumentPage]:
	"""Rasterize a Paperless document (always a PDF) into one image page per PDF page."""
	return [DocumentPage(image=page, data_url=to_data_url(page, RASTER_MIME_TYPE)) for page in rasterize_pdf(content)]
