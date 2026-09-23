import asyncio
import json
import logging

from bujo_digitizer.connectors import DigitizeJobRow, DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.models import DigitizeRequest
from bujo_digitizer.utils import MAX_BYTES, to_pages

logger = logging.getLogger(__name__)


class DigitizeWorker:
	"""Consumes digitize jobs from SQLite and runs them in the background."""

	def __init__(
		self,
		jobs: DigitizeJobStore,
		store: DigitizeResultStore,
		controller: DigitizeController,
		paperless_controller: PaperlessController,
		*,
		poll_interval: float = 2.0,
		concurrency: int = 1,
	) -> None:
		self._jobs: DigitizeJobStore = jobs
		self._store: DigitizeResultStore = store
		self._controller: DigitizeController = controller
		self._paperless_controller: PaperlessController = paperless_controller
		self._poll_interval: float = poll_interval
		self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)
		self._loop_task: asyncio.Task[None] | None = None
		self._tasks: set[asyncio.Task[None]] = set()

	async def start(self) -> None:
		reclaimed = await asyncio.to_thread(self._jobs.requeue_running)
		if reclaimed:
			logger.info("Reclaimed %d interrupted digitize job(s)", reclaimed)
		self._loop_task = asyncio.create_task(self._run(), name="digitize-worker")

	async def aclose(self) -> None:
		if self._loop_task is not None:
			_ = self._loop_task.cancel()
			_ = await asyncio.gather(self._loop_task, return_exceptions=True)
			self._loop_task = None
		# In-flight jobs are left marked running; start() requeues them on the next boot.
		for task in list(self._tasks):
			_ = task.cancel()
		if self._tasks:
			_ = await asyncio.gather(*self._tasks, return_exceptions=True)

	async def _run(self) -> None:
		while True:
			job = await asyncio.to_thread(self._jobs.claim_next)
			if job is None:
				await asyncio.sleep(self._poll_interval)
				continue
			_ = await self._semaphore.acquire()
			task = asyncio.create_task(self._process(job))
			self._tasks.add(task)
			task.add_done_callback(self._on_task_done)

	def _on_task_done(self, task: asyncio.Task[None]) -> None:
		self._tasks.discard(task)
		self._semaphore.release()
		if task.cancelled():
			return
		error = task.exception()
		if error is not None:
			logger.error("Digitize job task crashed: %s", error, exc_info=error)

	async def _process(self, job: DigitizeJobRow) -> None:
		doc_id = job["paperless_doc_id"]
		job_id = job["id"]
		logger.info("Digitize job %d started for Paperless doc %d (attempt %d)", job_id, doc_id, job["attempts"])
		try:
			content, _ = await self._paperless_controller.download_document(doc_id)

			if len(content) > MAX_BYTES:
				raise ValueError(
					f"Document's size is {len(content)} bytes. It's larger than {MAX_BYTES / (1024 * 1024)} MB."
				)

			pages = await asyncio.to_thread(to_pages, content)
			result = await self._controller.digitize(DigitizeRequest(file_urls=[page.data_url for page in pages]))

			parse_result = (
				result.parser_output.model_dump_json(ensure_ascii=False, indent=4)
				if result.parser_output is not None
				else None
			)
			bbox_elements = json.dumps([str(page) for page in result.ocr_results_with_bb])
			_ = await asyncio.to_thread(
				self._store.save,
				doc_id,
				job["doc_title"],
				parse_result,
				bbox_elements,
				[page.image for page in pages],
			)
		except Exception as exc:
			logger.exception("Digitize job %d failed for Paperless doc %d", job_id, doc_id)
			await asyncio.to_thread(self._jobs.fail, job_id, str(exc))
		else:
			await asyncio.to_thread(self._jobs.complete, job_id)
			logger.info("Digitize job %d finished for Paperless doc %d", job_id, doc_id)
