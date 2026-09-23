import asyncio
import logging
from importlib import resources

import filetype
from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bujo_digitizer.config import get_settings
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.exceptions import PaperlessControllerException
from bujo_digitizer.models import DigitizeRequest, HealthResponse, PaperlessWebhookPayload, ParserOutput
from bujo_digitizer.utils import to_data_url, to_pages

MAX_BYTES = 15 * 1024 * 1024  # 15 MB
# 12 bytes should be enough to determine the mime type of an image file (up to JPEG-XL).
MIME_TYPE_BYTES = 12

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter()
controller = DigitizeController()
paperless_controller = PaperlessController(settings.paperless_base_url, settings.paperless_token)
templates = Jinja2Templates(directory=str(resources.files("bujo_digitizer").joinpath("templates")))


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

	return {
		"doc_id": payload.doc_id,
		"parser_output": result.parser_output.root if result.parser_output is not None else None,
		"ocr_html": [str(page) for page in result.ocr_results_with_bb],
	}

