import sqlite3
from collections.abc import Callable

import anyio
import pytest

from bujo_digitizer.connectors import JOB_STATUS_DONE, JOB_STATUS_FAILED, DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.models import DigitizeRequest, DigitizeResponse, ParserOutput
from bujo_digitizer.worker import DigitizeWorker


class FakePaperlessController:
	def __init__(self, content: bytes = b"%PDF-1.7", error: Exception | None = None) -> None:
		self.content = content
		self.error = error
		self.created_requests: list[int] = []

	async def download_document(self, doc_id: int) -> tuple[bytes, str]:
		if self.error is not None:
			raise self.error
		return self.content, "application/pdf"

	async def get_created(self, doc_id: int) -> str:
		self.created_requests.append(doc_id)
		return "2026-01-05"


class FakeDigitizeController:
	def __init__(self) -> None:
		self.requests: list[DigitizeRequest] = []

	async def digitize(self, request: DigitizeRequest) -> DigitizeResponse:
		self.requests.append(request)
		return DigitizeResponse(parser_output=ParserOutput(root=[]), ocr_results_with_bb=[])


class FlakyJobStore:
	"""Fails the first claim and delegates everything else, like a briefly locked database."""

	def __init__(self, store: DigitizeJobStore) -> None:
		self._store: DigitizeJobStore = store
		self._failures: int = 1

	def __getattr__(self, name: str) -> object:
		return getattr(self._store, name)

	def claim_next(self):
		if self._failures:
			self._failures -= 1
			raise sqlite3.OperationalError("database is locked")
		return self._store.claim_next()


async def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
	with anyio.fail_after(timeout):
		while not predicate():
			await anyio.sleep(0.01)


@pytest.fixture
def stores(tmp_path):
	store = DigitizeResultStore(str(tmp_path / "results.sqlite3"))
	store.initialize()
	jobs = DigitizeJobStore(str(tmp_path / "jobs.sqlite3"))
	jobs.initialize()
	return store, jobs


@pytest.mark.anyio
async def test_start_processes_a_queued_job_and_saves_the_result(stores, pdf_bytes: bytes) -> None:
	store, jobs = stores
	job_id = jobs.enqueue(7, "My document", "2026-01-05")
	controller = FakeDigitizeController()
	worker = DigitizeWorker(
		jobs,
		store,
		controller,
		FakePaperlessController(pdf_bytes),
		poll_interval=0.01,
	)

	await worker.start()
	try:
		await _wait_until(lambda: jobs.get(job_id)["status"] == JOB_STATUS_DONE)
	finally:
		await worker.aclose()

	job = jobs.get(job_id)
	assert job is not None
	assert job["status"] == JOB_STATUS_DONE
	rows = store.list_all()
	assert len(rows) == 1
	assert rows[0]["paperless_doc_id"] == 7
	assert rows[0]["doc_title"] == "My document"
	assert rows[0]["doc_created"] == "2026-01-05"
	assert store.page_count(rows[0]["id"]) == 2
	assert len(controller.requests) == 1
	assert len(controller.requests[0].file_urls) == 2


@pytest.mark.anyio
async def test_claim_failure_does_not_stop_the_consumer_loop(stores, pdf_bytes: bytes) -> None:
	store, jobs = stores
	flaky = FlakyJobStore(jobs)
	worker = DigitizeWorker(
		flaky,
		store,
		FakeDigitizeController(),
		FakePaperlessController(pdf_bytes),
		poll_interval=0.01,
	)

	await worker.start()
	try:
		job_id = jobs.enqueue(7, "My document", "2026-01-05")
		await _wait_until(lambda: jobs.get(job_id)["status"] == JOB_STATUS_DONE)
	finally:
		await worker.aclose()

	assert jobs.get(job_id)["status"] == JOB_STATUS_DONE


@pytest.mark.anyio
async def test_start_requeues_interrupted_running_jobs(stores, pdf_bytes: bytes) -> None:
	store, jobs = stores
	job_id = jobs.enqueue(7, "My document", "")
	claimed = jobs.claim_next()
	assert claimed is not None
	worker = DigitizeWorker(
		jobs, store, FakeDigitizeController(), FakePaperlessController(pdf_bytes), poll_interval=0.01
	)

	await worker.start()
	try:
		await _wait_until(lambda: jobs.get(job_id)["status"] == JOB_STATUS_DONE)
	finally:
		await worker.aclose()

	assert jobs.get(job_id)["status"] == JOB_STATUS_DONE


@pytest.mark.anyio
async def test_failed_job_is_marked_failed_after_the_last_attempt(stores) -> None:
	store, jobs = stores
	job_id = jobs.enqueue(7, "My document", "", max_attempts=1)
	worker = DigitizeWorker(
		jobs,
		store,
		FakeDigitizeController(),
		FakePaperlessController(error=RuntimeError("paperless exploded")),
		poll_interval=0.01,
	)

	await worker.start()
	try:
		await _wait_until(lambda: jobs.get(job_id)["status"] == JOB_STATUS_FAILED)
	finally:
		await worker.aclose()

	job = jobs.get(job_id)
	assert job is not None
	assert job["status"] == JOB_STATUS_FAILED
	assert "paperless exploded" in (job["last_error"] or "")
	assert store.list_all() == []


@pytest.mark.anyio
async def test_aclose_is_safe_without_start(stores) -> None:
	store, jobs = stores
	worker = DigitizeWorker(jobs, store, FakeDigitizeController(), FakePaperlessController())

	await worker.aclose()

	assert jobs.list_jobs() == []


@pytest.mark.anyio
async def test_aclose_stops_the_background_loop(stores) -> None:
	store, jobs = stores
	worker = DigitizeWorker(jobs, store, FakeDigitizeController(), FakePaperlessController(), poll_interval=0.01)

	await worker.start()
	await worker.aclose()
	# a closed worker can be started again (state was reset cleanly)
	await worker.start()
	await worker.aclose()

	assert jobs.list_jobs() == []
