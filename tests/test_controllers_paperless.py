import json

import httpx2
import pytest

from bujo_digitizer.controllers import PaperlessController, PaperlessControllerException


def _controller(handler) -> PaperlessController:
	controller = PaperlessController("http://paperless.test", "secret")
	controller._client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
	return controller


@pytest.mark.anyio
async def test_download_document_returns_content_and_mime_type() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		assert request.method == "GET"
		assert request.url.path == "/api/documents/12/download/"
		assert request.headers["Authorization"] == "Token secret"
		return httpx2.Response(
			200,
			content=b"%PDF-1.7",
			headers={"content-type": "application/pdf"},
			request=request,
		)

	controller = _controller(handler)
	try:
		content, mime = await controller.download_document(12)
	finally:
		await controller.aclose()

	assert content == b"%PDF-1.7"
	assert mime == "application/pdf"


@pytest.mark.anyio
async def test_download_document_surfaces_http_status_errors() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		return httpx2.Response(404, request=request)

	controller = _controller(handler)
	try:
		with pytest.raises(PaperlessControllerException, match="404"):
			await controller.download_document(12)
	finally:
		await controller.aclose()


@pytest.mark.anyio
async def test_download_document_surfaces_connection_errors() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		raise httpx2.ConnectError("offline", request=request)

	controller = _controller(handler)
	try:
		with pytest.raises(PaperlessControllerException, match="Failed to reach Paperless API"):
			await controller.download_document(12)
	finally:
		await controller.aclose()


@pytest.mark.anyio
async def test_update_document_content_patches_the_document() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		assert request.method == "PATCH"
		assert request.url.path == "/api/documents/12/"
		assert json.loads(request.content) == {"content": "# Bujo"}
		return httpx2.Response(200, request=request)

	controller = _controller(handler)
	try:
		await controller.update_document_content(12, "# Bujo")
	finally:
		await controller.aclose()


@pytest.mark.anyio
async def test_add_document_tag_uses_bulk_edit() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		assert request.method == "POST"
		assert request.url.path == "/api/documents/bulk_edit/"
		assert json.loads(request.content) == {
			"documents": [12],
			"method": "add_tag",
			"parameters": {"tag": 6},
		}
		return httpx2.Response(200, request=request)

	controller = _controller(handler)
	try:
		await controller.add_document_tag(12, 6)
	finally:
		await controller.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
	("created", "expected"),
	[
		("2026-01-05", "2026-01-05"),
		("2026-01-05T12:34:56Z", "2026-01-05"),
		(None, ""),
	],
)
async def test_get_created_normalizes_to_a_date(created: str | None, expected: str) -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		return httpx2.Response(200, json={"created": created}, request=request)

	controller = _controller(handler)
	try:
		assert await controller.get_created(12) == expected
	finally:
		await controller.aclose()


@pytest.mark.anyio
async def test_get_created_rejects_invalid_json() -> None:
	async def handler(request: httpx2.Request) -> httpx2.Response:
		return httpx2.Response(200, content=b"not json", request=request)

	controller = _controller(handler)
	try:
		with pytest.raises(PaperlessControllerException, match="invalid JSON"):
			await controller.get_created(12)
	finally:
		await controller.aclose()
