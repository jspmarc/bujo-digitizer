from bujo_digitizer.utils import RASTER_MIME_TYPE, DocumentPage, rasterize_pdf, to_data_url, to_pages


def test_to_data_url_encodes_base64() -> None:
	assert to_data_url(b"hello", "text/plain") == "data:text/plain;base64,aGVsbG8="


def test_rasterize_pdf_returns_one_jpeg_per_page(pdf_bytes: bytes) -> None:
	pages = rasterize_pdf(pdf_bytes, dpi=36)

	assert len(pages) == 2
	assert all(page.startswith(b"\xff\xd8") for page in pages)


def test_to_pages_wraps_every_page_in_a_data_url(pdf_bytes: bytes) -> None:
	pages = to_pages(pdf_bytes)

	assert len(pages) == 2
	assert all(isinstance(page, DocumentPage) for page in pages)
	assert all(page.data_url.startswith(f"data:{RASTER_MIME_TYPE};base64,") for page in pages)
	assert all(page.image.startswith(b"\xff\xd8") for page in pages)
