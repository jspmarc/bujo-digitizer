import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import (
	ObsidianController,
	ObsidianControllerException,
	PaperlessController,
	PaperlessControllerException,
)
from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import ParserOutput
from bujo_digitizer.router.common import render_reviews
from bujo_digitizer.utils import RASTER_MIME_TYPE

logger = get_logger(__name__)


class ReviewsRouter:
	"""Review listing, detail, approval, and deletion routes."""

	def __init__(
		self,
		*,
		settings: Settings,
		paperless_controller: PaperlessController,
		obsidian_controller: ObsidianController,
		store: DigitizeResultStore,
		templates: Jinja2Templates,
		jobs: DigitizeJobStore,
	) -> None:
		self._settings: Settings = settings
		self._paperless_controller: PaperlessController = paperless_controller
		self._obsidian_controller: ObsidianController = obsidian_controller
		self._store: DigitizeResultStore = store
		self._templates: Jinja2Templates = templates
		self._jobs: DigitizeJobStore = jobs
		self._router: APIRouter = APIRouter()
		self._register_routes()

	@property
	def router(self) -> APIRouter:
		return self._router

	def _register_routes(self) -> None:
		r = self._router
		r.add_api_route("/reviews", self.reviews_list, methods=["GET"])
		r.add_api_route("/reviews/{id}", self.review_page, methods=["GET"], include_in_schema=False)
		r.add_api_route("/reviews/{id}/content", self.review_content, methods=["GET"])
		r.add_api_route("/reviews/{id}/page/{page_index}", self.review_page_image, methods=["GET"])
		r.add_api_route("/reviews/{id}/document", self.review_document, methods=["GET"])
		r.add_api_route("/reviews/{id}", self.review_delete, methods=["DELETE"])
		r.add_api_route("/reviews/{id}", self.review_update, methods=["POST"])

	async def reviews_list(self, request: Request):
		return await render_reviews(request, self._store, self._jobs, self._templates)

	async def review_page(self, request: Request, id: int):
		row = await asyncio.to_thread(self._store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		return self._templates.TemplateResponse(
			request,
			"review_detail.html",
			{"id": id, "doc_title": row["doc_title"], "doc_id": row["paperless_doc_id"]},
		)

	async def review_content(self, request: Request, id: int):
		row = await asyncio.to_thread(self._store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		if row["parse_result"]:
			try:
				row["parse_result"] = json.dumps(json.loads(row["parse_result"]), ensure_ascii=False, indent=4)
			except json.JSONDecodeError:
				pass
		bbox_pages = json.loads(row["bbox_elements"]) if row["bbox_elements"] else []
		page_count = await asyncio.to_thread(self._store.page_count, id)
		pages = [
			{"index": index, "bbox_html": bbox_pages[index] if index < len(bbox_pages) else ""}
			for index in range(page_count)
		]
		return self._templates.TemplateResponse(
			request,
			"_review_detail.html",
			{"row": row, "pages": pages, "paperless_base_url": self._settings.paperless_base_url},
		)

	async def review_page_image(self, id: int, page_index: int):
		image = await asyncio.to_thread(self._store.get_page, id, page_index)
		if image is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
		return Response(content=image, media_type=RASTER_MIME_TYPE)

	async def review_document(self, id: int):
		row = await asyncio.to_thread(self._store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		try:
			content, mime = await self._paperless_controller.download_document(row["paperless_doc_id"])
		except PaperlessControllerException as exc:
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=str(exc),
			)
		return Response(content=content, media_type=mime or "application/pdf")

	async def review_delete(self, id: int):
		row = await asyncio.to_thread(self._store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
		await asyncio.to_thread(self._store.delete, id)
		return HTMLResponse(content="Deleted.")

	async def review_update(self, id: int, parse_result: Annotated[str, Form()]):
		row = await asyncio.to_thread(self._store.get, id)
		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")

		try:
			content_raw = ParserOutput.model_validate_json(parse_result or "[]")
			content = content_raw.to_markdown()
		except ValidationError as exc:
			raise HTTPException(
				status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
				detail=str(exc),
			)

		try:
			await self._paperless_controller.update_document_content(row["paperless_doc_id"], content)
			await self._paperless_controller.add_document_tag(
				row["paperless_doc_id"], self._settings.paperless_digitized_tag_id
			)
			if self._settings.obsidian_bujo_enabled:
				doc_created = row["doc_created"]
				if not doc_created:
					# legacy rows without `doc_created`: ask Paperless so the Obsidian update is never skipped
					doc_created = await self._paperless_controller.get_created(row["paperless_doc_id"])
				await asyncio.to_thread(self._obsidian_controller.modify_obsidian, doc_created, content_raw)
		except PaperlessControllerException as exc:
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=str(exc),
			)
		except ObsidianControllerException as exc:
			# Obsidian is required when enabled: surface the failure so the review can be re-approved
			logger.exception("Failed to update Obsidian for doc %s", row["paperless_doc_id"])
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=f"Failed to update Obsidian: {exc}",
			) from exc

		return HTMLResponse(content="Updated.")
