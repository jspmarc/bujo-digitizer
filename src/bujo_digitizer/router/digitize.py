import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.templating import Jinja2Templates

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import JOB_STATUS_FAILED, JOB_STATUS_PENDING, DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController
from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import HealthResponse, PaperlessWebhookPayload
from bujo_digitizer.router.common import render_reviews

logger = get_logger(__name__)


class DigitizeRouter:
	"""Health, digitize webhook, and digitize job routes."""

	def __init__(
		self,
		*,
		settings: Settings,
		controller: DigitizeController,
		store: DigitizeResultStore,
		jobs: DigitizeJobStore,
		templates: Jinja2Templates,
	) -> None:
		self._settings: Settings = settings
		self._controller: DigitizeController = controller
		self._store: DigitizeResultStore = store
		self._jobs: DigitizeJobStore = jobs
		self._templates: Jinja2Templates = templates
		self._router: APIRouter = APIRouter()
		self._register_routes()

	@property
	def router(self) -> APIRouter:
		return self._router

	def _register_routes(self) -> None:
		r = self._router
		r.add_api_route("/health", self.health, methods=["GET"], response_model=HealthResponse)
		r.add_api_route(
			"/digitize/webhook",
			self.digitize_webhook,
			methods=["POST"],
			status_code=status.HTTP_202_ACCEPTED,
		)
		r.add_api_route("/jobs/{id}/retry", self.job_retry, methods=["POST"])
		r.add_api_route("/jobs/{id}", self.job_delete, methods=["DELETE"])

	async def health(self) -> HealthResponse:
		return await self._controller.health()

	async def digitize_webhook(self, payload: PaperlessWebhookPayload):
		logger.info("Payload is %s", payload)
		job_id = await asyncio.to_thread(
			self._jobs.enqueue,
			payload.doc_id,
			payload.doc_title,
			payload.created.isoformat() if payload.created is not None else "",
			self._settings.job_max_attempts,
		)
		# enqueue dedupes onto an existing active job, so report that job's real status.
		job = await asyncio.to_thread(self._jobs.get, job_id)
		job_status = job["status"] if job is not None else JOB_STATUS_PENDING
		return {"job_id": job_id, "doc_id": payload.doc_id, "status": job_status}

	async def job_retry(self, request: Request, id: int):
		job = await asyncio.to_thread(self._jobs.get, id)
		if job is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {id} not found.")
		if job["status"] != JOB_STATUS_FAILED:
			raise HTTPException(
				status_code=status.HTTP_409_CONFLICT,
				detail=f"Job {id} is '{job['status']}'; only failed jobs can be retried.",
			)
		retried = await asyncio.to_thread(self._jobs.retry, id)
		if not retried:
			raise HTTPException(
				status_code=status.HTTP_409_CONFLICT,
				detail=f"Another job for document {job['paperless_doc_id']} is pending or running.",
			)
		return await render_reviews(request, self._store, self._jobs, self._templates)

	async def job_delete(self, request: Request, id: int):
		job = await asyncio.to_thread(self._jobs.get, id)
		if job is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {id} not found.")
		await asyncio.to_thread(self._jobs.delete, id)
		return await render_reviews(request, self._store, self._jobs, self._templates)
