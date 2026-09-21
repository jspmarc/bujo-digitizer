import logging
from base64 import b64encode
from importlib import resources

import filetype
from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.templating import Jinja2Templates

from bujo_digitizer.controllers import DigitizeController
from bujo_digitizer.models import DigitizeRequest, DigitizeResponse, HealthResponse

MAX_BYTES = 15 * 1024 * 1024  # 15 MB
# 12 bytes should be enough to determine the mime type of an image file (up to JPEG-XL).
MIME_TYPE_BYTES = 12

logger = logging.getLogger(__name__)
router = APIRouter()
controller = DigitizeController()
templates = Jinja2Templates(directory=str(resources.files("bujo_digitizer").joinpath("templates")))


@router.get("/", include_in_schema=False)
async def index(request: Request):
	return templates.TemplateResponse(request, "index.html")


@router.get("/health", response_model=HealthResponse)
async def health():
	return await controller.health()


@router.post("/digitize", response_model=DigitizeResponse)
async def digitize(request: DigitizeRequest):
	return await controller.digitize(request)


@router.post("/digitize/html", include_in_schema=False)
async def digitize_html(request: Request, image: UploadFile):
	content = await image.read()
	if image.size is None or image.size > MAX_BYTES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
			detail=f"Image's size is {image.size} bytes. It's larger than {MAX_BYTES / (1024 * 1024)} MB.",
		)

	mime = image.content_type or filetype.guess_mime(content[:MIME_TYPE_BYTES])
	b64 = b64encode(content).decode("ascii")
	image_url = f"data:{mime};base64,{b64}"
	logger.info("first 20 characters of base64-encoded URL: %s", b64[:20])
	response = await controller.digitize(DigitizeRequest(image_url=image_url))
	return templates.TemplateResponse(request, "digitize_result.html", {"data": response.content})
