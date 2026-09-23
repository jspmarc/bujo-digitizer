import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import JOB_STATUS_FAILED, DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.exceptions import PaperlessControllerException
from bujo_digitizer.models import HealthResponse, PaperlessWebhookPayload, ParserOutput
from bujo_digitizer.utils import RASTER_MIME_TYPE

# 12 bytes should be enough to determine the mime type of an image file (up to JPEG-XL).
MIME_TYPE_BYTES = 12

logger = logging.getLogger(__name__)


class Router:
	"""HTTP routes for the digitizer. Dependencies are injected from main.py."""

	def __init__(
		self,
		*,
		settings: Settings,
		controller: DigitizeController,
		paperless_controller: PaperlessController,
		store: DigitizeResultStore,
		jobs: DigitizeJobStore,
		templates: Jinja2Templates,
	) -> None:
		self.settings = settings
		self.controller = controller
		self.paperless_controller = paperless_controller
		self.store = store
		self.jobs = jobs
		self.templates = templates
		self.router = APIRouter()
		self._register_routes()

	def _register_routes(self) -> None:
		r = self.router
		r.add_api_route("/", self.index, methods=["GET"], include_in_schema=False)
		r.add_api_route("/health", self.health, methods=["GET"], response_model=HealthResponse)
		r.add_api_route(
			"/digitize/webhook",
			self.digitize_webhook,
			methods=["POST"],
			status_code=status.HTTP_202_ACCEPTED,
		)
		r.add_api_route("/reviews", self.reviews_list, methods=["GET"])
		r.add_api_route("/reviews/{id}", self.review_page, methods=["GET"], include_in_schema=False)
		r.add_api_route("/reviews/{id}/content", self.review_content, methods=["GET"])
		r.add_api_route("/reviews/{id}/page/{page_index}", self.review_page_image, methods=["GET"])
		r.add_api_route("/reviews/{id}/document", self.review_document, methods=["GET"])
		r.add_api_route("/reviews/{id}", self.review_update, methods=["POST"])
		r.add_api_route("/reviews/{id}", self.review_delete, methods=["DELETE"])
		r.add_api_route("/jobs/{id}/retry", self.job_retry, methods=["POST"])
		r.add_api_route("/jobs/{id}", self.job_delete, methods=["DELETE"])

	async def index(self, request: Request):
		return self.templates.TemplateResponse(request, "index.html")

	async def health(self) -> HealthResponse:
		return await self.controller.health()

	async def digitize_webhook(self, payload: PaperlessWebhookPayload):
		logger.info(f"Payload is {payload}")
		job_id = await asyncio.to_thread(
			self.jobs.enqueue,
			payload.doc_id,
			payload.doc_title,
			self.settings.job_max_attempts,
		)
		return {"job_id": job_id, "doc_id": payload.doc_id, "status": "pending"}

	async def _render_reviews(self, request: Request):
		rows = await asyncio.to_thread(self.store.list_all)
		open_jobs = await asyncio.to_thread(self.jobs.list_jobs)
		return self.templates.TemplateResponse(request, "_review_list.html", {"rows": rows, "jobs": open_jobs})

	async def reviews_list(self, request: Request):
		return await self._render_reviews(request)

	async def review_page(self, request: Request, id: int):
		row = await asyncio.to_thread(self.store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		return self.templates.TemplateResponse(
			request,
			"review_detail.html",
			{"id": id, "doc_title": row["doc_title"], "doc_id": row["paperless_doc_id"]},
		)

	async def review_content(self, request: Request, id: int):
		row = await asyncio.to_thread(self.store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		if row["parse_result"]:
			try:
				row["parse_result"] = json.dumps(json.loads(row["parse_result"]), ensure_ascii=False, indent=4)
			except json.JSONDecodeError:
				pass
		bbox_pages = json.loads(row["bbox_elements"]) if row["bbox_elements"] else []
		page_count = await asyncio.to_thread(self.store.page_count, id)
		pages = [
			{"index": index, "bbox_html": bbox_pages[index] if index < len(bbox_pages) else ""}
			for index in range(page_count)
		]
		return self.templates.TemplateResponse(
			request,
			"_review_detail.html",
			{"row": row, "pages": pages, "paperless_base_url": self.settings.paperless_base_url},
		)

	async def review_page_image(self, id: int, page_index: int):
		image = await asyncio.to_thread(self.store.get_page, id, page_index)
		if image is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
		return Response(content=image, media_type=RASTER_MIME_TYPE)

	async def review_document(self, id: int):
		row = await asyncio.to_thread(self.store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		try:
			content, mime = await self.paperless_controller.download_document(row["paperless_doc_id"])
		except PaperlessControllerException as exc:
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=str(exc),
			)
		return Response(content=content, media_type=mime or "application/pdf")

	async def review_update(self, id: int, parse_result: Annotated[str, Form()]):
		DIGITIZED_TAG_ID = 6

		row = await asyncio.to_thread(self.store.get, id)
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
			await self.paperless_controller.update_document_content(row["paperless_doc_id"], content)
			await self.paperless_controller.add_document_tag(row["paperless_doc_id"], DIGITIZED_TAG_ID)
		except PaperlessControllerException as exc:
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=str(exc),
			)

		await asyncio.to_thread(self.store.delete, id)
		return HTMLResponse(content="Updated.")

	async def review_delete(self, id: int):
		await asyncio.to_thread(self.store.delete, id)
		return HTMLResponse(content="Deleted.")

	async def job_retry(self, request: Request, id: int):
		job = await asyncio.to_thread(self.jobs.get, id)
		if job is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {id} not found.")
		if job["status"] != JOB_STATUS_FAILED:
			raise HTTPException(
				status_code=status.HTTP_409_CONFLICT,
				detail=f"Job {id} is '{job['status']}'; only failed jobs can be retried.",
			)
		await asyncio.to_thread(self.jobs.retry, id)
		return await self._render_reviews(request)

	async def job_delete(self, request: Request, id: int):
		job = await asyncio.to_thread(self.jobs.get, id)
		if job is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {id} not found.")
		await asyncio.to_thread(self.jobs.delete, id)
		return await self._render_reviews(request)
