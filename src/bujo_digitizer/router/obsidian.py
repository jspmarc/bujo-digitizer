import asyncio
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import DigitizeResultStore
from bujo_digitizer.controllers import (
	ObsidianController,
	ObsidianControllerException,
	PaperlessController,
	PaperlessControllerException,
)
from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import ParserOutput

logger = get_logger(__name__)

DIGITIZED_TAG_ID = 6


class ObsidianRouter:
	"""The review approval route that pushes content to Paperless and Obsidian."""

	def __init__(
		self,
		*,
		settings: Settings,
		paperless_controller: PaperlessController,
		obsidian_controller: ObsidianController,
		store: DigitizeResultStore,
	) -> None:
		self._settings: Settings = settings
		self._paperless_controller: PaperlessController = paperless_controller
		self._obsidian_controller: ObsidianController = obsidian_controller
		self._store: DigitizeResultStore = store
		self._router: APIRouter = APIRouter()
		self._register_routes()

	@property
	def router(self) -> APIRouter:
		return self._router

	def _register_routes(self) -> None:
		self._router.add_api_route("/reviews/{id}", self.review_update, methods=["POST"])

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
			await self._paperless_controller.add_document_tag(row["paperless_doc_id"], DIGITIZED_TAG_ID)
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
