import asyncio
import json
import logging
from importlib import resources

import filetype
from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from bujo_digitizer.config import get_settings
from bujo_digitizer.connectors import DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.exceptions import PaperlessControllerException
from bujo_digitizer.models import DigitizeRequest, HealthResponse, PaperlessWebhookPayload, ParserOutput
from bujo_digitizer.utils import RASTER_MIME_TYPE, to_data_url, to_pages

MAX_BYTES = 15 * 1024 * 1024  # 15 MB
# 12 bytes should be enough to determine the mime type of an image file (up to JPEG-XL).
MIME_TYPE_BYTES = 12

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter()
controller = DigitizeController()
paperless_controller = PaperlessController(settings.paperless_base_url, settings.paperless_token)
templates = Jinja2Templates(directory=str(resources.files("bujo_digitizer").joinpath("templates")))
store = DigitizeResultStore(settings.sqlite_path)
store.initialize()


async def close_resources() -> None:
	await asyncio.gather(controller.aclose(), paperless_controller.aclose())


@router.get("/", include_in_schema=False)
async def index(request: Request):
	return templates.TemplateResponse(request, "index.html")


@router.get("/health", response_model=HealthResponse)
async def health():
	return await controller.health()


@router.post("/digitize/html")
async def digitize_html(request: Request, image: UploadFile):
	content = await image.read()
	if image.size is None or image.size > MAX_BYTES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
			detail=f"Image's size is {image.size} bytes. It's larger than {MAX_BYTES / (1024 * 1024)} MB.",
		)

	mime = image.content_type or filetype.guess_mime(content[:MIME_TYPE_BYTES]) or "application/octet-stream"
	image_url = to_data_url(content, mime)
	logger.info("Digitizing uploaded image (%s, %s bytes)", mime, len(content))
	digitize_response = await controller.digitize(DigitizeRequest(file_urls=[image_url]))

	parsed = (
		digitize_response.parser_output.model_dump_json(ensure_ascii=False, indent=4)
		if digitize_response.parser_output is not None
		else "null"
	)
	ocr_html = str(digitize_response.ocr_results_with_bb[0]) if digitize_response.ocr_results_with_bb else ""

	response = f"""<pre>
{parsed}
</pre>
<script type="text/html" id="ocr-html">{ocr_html}</script>"""

	return HTMLResponse(content=response)


@router.post("/digitize/webhook")
async def digitize_webhook(payload: PaperlessWebhookPayload):
	logger.info(f"Payload is {payload}")

	try:
		content, _ = await paperless_controller.download_document(payload.doc_id)
	except PaperlessControllerException as exc:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=str(exc),
		)

	if len(content) > MAX_BYTES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
			detail=f"Document's size is {len(content)} bytes. It's larger than {MAX_BYTES / (1024 * 1024)} MB.",
		)

	pages = await asyncio.to_thread(to_pages, content)
	result = await controller.digitize(DigitizeRequest(file_urls=[page.data_url for page in pages]))

	parse_result = (
		result.parser_output.model_dump_json(ensure_ascii=False, indent=4) if result.parser_output is not None else None
	)
	bbox_elements = json.dumps([str(page) for page in result.ocr_results_with_bb])
	row_id = await asyncio.to_thread(
		store.save, payload.doc_id, parse_result, bbox_elements, [page.image for page in pages]
	)

	return {
		"id": row_id,
		"doc_id": payload.doc_id,
		"parser_output": result.parser_output.root if result.parser_output is not None else None,
		"ocr_html": [str(page) for page in result.ocr_results_with_bb],
	}


@router.get("/reviews", include_in_schema=False)
async def reviews_page(request: Request):
	return templates.TemplateResponse(request, "review.html")


@router.get("/reviews/list")
async def reviews_list(request: Request):
	rows = await asyncio.to_thread(store.list_all)
	return templates.TemplateResponse(request, "_review_list.html", {"rows": rows})


@router.get("/reviews/{id}", include_in_schema=False)
async def review_page(request: Request, id: int):
	return templates.TemplateResponse(request, "review_detail.html", {"id": id})


@router.get("/reviews/{id}/content")
async def review_content(request: Request, id: int):
	row = await asyncio.to_thread(store.get, id)
	if row is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
	if row["parse_result"]:
		try:
			row["parse_result"] = json.dumps(json.loads(row["parse_result"]), ensure_ascii=False, indent=4)
		except json.JSONDecodeError:
			pass
	bbox_pages = json.loads(row["bbox_elements"]) if row["bbox_elements"] else []
	page_count = await asyncio.to_thread(store.page_count, id)
	pages = [
		{"index": index, "bbox_html": bbox_pages[index] if index < len(bbox_pages) else ""}
		for index in range(page_count)
	]
	return templates.TemplateResponse(request, "_review_detail.html", {"row": row, "pages": pages})


@router.get("/reviews/{id}/page/{page_index}")
async def review_page_image(id: int, page_index: int):
	image = await asyncio.to_thread(store.get_page, id, page_index)
	if image is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
	return Response(content=image, media_type=RASTER_MIME_TYPE)


@router.get("/reviews/{id}/document")
async def review_document(id: int):
	row = await asyncio.to_thread(store.get, id)
	if row is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
	try:
		content, mime = await paperless_controller.download_document(row["paperless_doc_id"])
	except PaperlessControllerException as exc:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=str(exc),
		)
	return Response(content=content, media_type=mime or "application/pdf")


@router.post("/reviews/{id}")
async def review_update(id: int, parse_result: str = Form("")):
	row = await asyncio.to_thread(store.get, id)
	if row is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")

	try:
		content = ParserOutput.model_validate_json(parse_result).to_markdown() if parse_result else ""
	except ValidationError as exc:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
			detail=str(exc),
		)

	try:
		await paperless_controller.update_document_content(row["paperless_doc_id"], content)
	except PaperlessControllerException as exc:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=str(exc),
		)

	await asyncio.to_thread(store.delete, id)
	return HTMLResponse(content="Updated.")
