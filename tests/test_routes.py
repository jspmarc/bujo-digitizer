import json
from dataclasses import dataclass, field
from importlib import resources

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.testclient import TestClient

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import (
	JOB_STATUS_FAILED,
	JOB_STATUS_PENDING,
	JOB_STATUS_RUNNING,
	DigitizeJobStore,
	DigitizeResultStore,
)
from bujo_digitizer.controllers import ObsidianControllerException, PaperlessControllerException
from bujo_digitizer.models import HealthResponse, ParserOutput
from bujo_digitizer.router import Router


class FakeDigitizeController:
	async def health(self) -> HealthResponse:
		return HealthResponse(status="ok")


class FakePaperlessController:
	def __init__(self, document: bytes = b"%PDF-1.7") -> None:
		self.document = document
		self.updated: list[tuple[int, str]] = []
		self.tagged: list[tuple[int, int]] = []
		self.created_requests: list[int] = []
		self.download_error: Exception | None = None
		self.update_error: Exception | None = None

	async def download_document(self, doc_id: int) -> tuple[bytes, str]:
		if self.download_error is not None:
			raise self.download_error
		return self.document, "application/pdf"

	async def update_document_content(self, doc_id: int, content: str) -> None:
		if self.update_error is not None:
			raise self.update_error
		self.updated.append((doc_id, content))

	async def add_document_tag(self, doc_id: int, tag_id: int) -> None:
		self.tagged.append((doc_id, tag_id))

	async def get_created(self, doc_id: int) -> str:
		self.created_requests.append(doc_id)
		return "2026-01-05"


class FakeObsidianController:
	def __init__(self) -> None:
		self.calls: list[tuple[str, ParserOutput]] = []
		self.error: Exception | None = None

	def modify_obsidian(self, doc_created: str, content: ParserOutput) -> None:
		if self.error is not None:
			raise self.error
		self.calls.append((doc_created, content))


@dataclass
class RouteContext:
	client: TestClient
	store: DigitizeResultStore
	jobs: DigitizeJobStore
	paperless: FakePaperlessController = field(default_factory=FakePaperlessController)
	obsidian: FakeObsidianController = field(default_factory=FakeObsidianController)


@pytest.fixture
def routes(tmp_path):
	settings = Settings(
		OPENAI_BASE_URL="http://openai.test/v1",
		PAPERLESS_BASE_URL="http://paperless.test",
		PAPERLESS_TOKEN="test-token",
		PAPERLESS_DIGITIZED_TAG_ID=6,
		OBSIDIAN_BUJO_ENABLED=True,
	)
	# Both stores share one file, like production, so the migration covers both tables.
	db_path = str(tmp_path / "db.sqlite3")
	store = DigitizeResultStore(db_path)
	store.initialize()
	jobs = DigitizeJobStore(db_path)
	paperless = FakePaperlessController()
	obsidian = FakeObsidianController()
	templates = Jinja2Templates(directory=str(resources.files("bujo_digitizer").joinpath("templates")))
	router = Router(
		settings=settings,
		controller=FakeDigitizeController(),
		paperless_controller=paperless,
		obsidian_controller=obsidian,
		store=store,
		jobs=jobs,
		templates=templates,
	)
	app = FastAPI()
	app.include_router(router.router)

	with TestClient(app) as client:
		yield RouteContext(client=client, store=store, jobs=jobs, paperless=paperless, obsidian=obsidian)


def _save_review(store: DigitizeResultStore, doc_created: str = "2026-01-05") -> int:
	return store.save(
		7,
		"My document",
		doc_created,
		'[{"time": "09:00", "bujos": [{"type": "THOUGHT", "note": "hi"}]}]',
		'["<div data-bbox=\\"0 0 1 1\\">ocr</div>"]',
		[b"\xff\xd8page"],
	)


def _failed_job(jobs: DigitizeJobStore) -> int:
	job_id = jobs.enqueue(7, "My document", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(job_id, "boom")
	return job_id


def test_index_page(routes: RouteContext) -> None:
	response = routes.client.get("/")

	assert response.status_code == 200
	assert "To Review" in response.text


def test_health(routes: RouteContext) -> None:
	response = routes.client.get("/health")

	assert response.status_code == 200
	assert response.json() == {"status": "ok"}


def test_digitize_webhook_enqueues_a_job(routes: RouteContext) -> None:
	response = routes.client.post(
		"/digitize/webhook",
		json={"doc_id": 7, "doc_title": "My document", "created": "2026-01-05"},
	)

	assert response.status_code == 202
	payload = response.json()
	assert payload["doc_id"] == 7
	assert payload["status"] == "pending"
	job = routes.jobs.get(payload["job_id"])
	assert job is not None
	assert job["doc_created"] == "2026-01-05"


def test_digitize_webhook_deduplicates_active_jobs(routes: RouteContext) -> None:
	first = routes.client.post("/digitize/webhook", json={"doc_id": 7, "doc_title": "My document"})
	second = routes.client.post("/digitize/webhook", json={"doc_id": 7, "doc_title": "My document"})

	assert first.json()["job_id"] == second.json()["job_id"]


def test_digitize_webhook_reports_the_existing_job_status(routes: RouteContext) -> None:
	first = routes.client.post("/digitize/webhook", json={"doc_id": 7, "doc_title": "My document"}).json()
	_ = routes.jobs.claim_next()

	second = routes.client.post("/digitize/webhook", json={"doc_id": 7, "doc_title": "My document"}).json()

	assert second["job_id"] == first["job_id"]
	assert second["status"] == JOB_STATUS_RUNNING


def test_reviews_list_shows_jobs_and_rows(routes: RouteContext) -> None:
	_ = _save_review(routes.store)
	_ = routes.jobs.enqueue(7, "My document", "")

	response = routes.client.get("/reviews")

	assert response.status_code == 200
	assert "My document" in response.text


def test_reviews_list_shows_failed_jobs_as_a_total_attempts(routes: RouteContext) -> None:
	job_id = _failed_job(routes.jobs)
	assert routes.jobs.retry_failed() == 1
	_ = routes.jobs.claim_next()
	routes.jobs.fail(job_id, "boom again")

	response = routes.client.get("/reviews")

	assert "2 attempts" in response.text
	assert "2/1" not in response.text
	assert "Digitizing" in response.text


def test_review_page(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.get(f"/reviews/{review_id}")

	assert response.status_code == 200
	assert "My document" in response.text


def test_review_content_renders_pages_and_bboxes(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.get(f"/reviews/{review_id}/content")

	assert response.status_code == 200
	assert "data-bbox" in response.text
	assert "hi" in response.text


def test_review_content_strips_unsafe_bbox_markup(routes: RouteContext) -> None:
	bbox_html = '<div data-bbox="0 0 1 1">ocr<img src=x onerror=alert(1)><script>alert(2)</script></div>'
	review_id = routes.store.save(7, "My document", "2026-01-05", None, json.dumps([bbox_html]), [b"\xff\xd8page"])

	response = routes.client.get(f"/reviews/{review_id}/content")

	assert response.status_code == 200
	assert 'data-bbox="0 0 1 1"' in response.text
	assert "ocr" in response.text
	assert "onerror" not in response.text
	assert "<script" not in response.text


def test_review_page_image(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.get(f"/reviews/{review_id}/page/0")

	assert response.status_code == 200
	assert response.headers["content-type"] == "image/jpeg"
	assert response.content == b"\xff\xd8page"


def test_review_document_downloads_from_paperless(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.get(f"/reviews/{review_id}/document")

	assert response.status_code == 200
	assert response.headers["content-type"] == "application/pdf"
	assert response.content == b"%PDF-1.7"


def test_review_update_pushes_to_paperless_and_obsidian(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.post(f"/reviews/{review_id}", data={"parse_result": "[]"})

	assert response.status_code == 200
	assert response.text == "Updated."
	assert routes.paperless.updated == [(7, "")]
	assert routes.paperless.tagged == [(7, 6)]
	assert len(routes.obsidian.calls) == 1
	assert routes.obsidian.calls[0][0] == "2026-01-05"


def test_review_update_fetches_the_created_date_when_missing(routes: RouteContext) -> None:
	review_id = _save_review(routes.store, doc_created="")

	response = routes.client.post(f"/reviews/{review_id}", data={"parse_result": "[]"})

	assert response.status_code == 200
	assert routes.paperless.created_requests == [7]
	assert routes.obsidian.calls[0][0] == "2026-01-05"


def test_review_update_rejects_invalid_parser_output(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.post(f"/reviews/{review_id}", data={"parse_result": "not json"})

	assert response.status_code == 422
	assert routes.paperless.updated == []


def test_review_update_surfaces_obsidian_errors(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)
	routes.obsidian.error = ObsidianControllerException("vault unavailable")

	response = routes.client.post(f"/reviews/{review_id}", data={"parse_result": "[]"})

	assert response.status_code == 500
	assert "Failed to update Obsidian" in response.json()["detail"]


def test_review_document_surfaces_paperless_errors(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)
	routes.paperless.download_error = PaperlessControllerException("paperless down")

	response = routes.client.get(f"/reviews/{review_id}/document")

	assert response.status_code == 500
	assert response.json()["detail"] == "paperless down"


def test_review_delete(routes: RouteContext) -> None:
	review_id = _save_review(routes.store)

	response = routes.client.delete(f"/reviews/{review_id}")

	assert response.status_code == 200
	assert response.text == "Deleted."
	assert routes.store.get(review_id) is None


def test_job_retry_requeues_a_failed_job(routes: RouteContext) -> None:
	job_id = _failed_job(routes.jobs)

	response = routes.client.post(f"/jobs/{job_id}/retry")

	assert response.status_code == 200
	assert routes.jobs.get(job_id)["status"] == JOB_STATUS_PENDING


def test_job_retry_rejects_a_job_that_is_not_failed(routes: RouteContext) -> None:
	job_id = routes.jobs.enqueue(7, "My document", "")

	response = routes.client.post(f"/jobs/{job_id}/retry")

	assert response.status_code == 409


def test_job_retry_rejects_a_job_while_another_one_is_active(routes: RouteContext) -> None:
	job_id = _failed_job(routes.jobs)
	_ = routes.jobs.enqueue(7, "My document", "")

	response = routes.client.post(f"/jobs/{job_id}/retry")

	assert response.status_code == 409
	assert routes.jobs.get(job_id)["status"] == JOB_STATUS_FAILED


def test_job_delete(routes: RouteContext) -> None:
	job_id = _failed_job(routes.jobs)

	response = routes.client.delete(f"/jobs/{job_id}")

	assert response.status_code == 200
	assert routes.jobs.get(job_id) is None


@pytest.mark.parametrize(
	("method", "path"),
	[
		("GET", "/reviews/999"),
		("GET", "/reviews/999/content"),
		("GET", "/reviews/999/page/0"),
		("GET", "/reviews/999/document"),
		("POST", "/reviews/999"),
		("DELETE", "/reviews/999"),
		("POST", "/jobs/999/retry"),
		("DELETE", "/jobs/999"),
	],
)
def test_missing_resources_return_404(routes: RouteContext, method: str, path: str) -> None:
	response = routes.client.request(method, path, data={"parse_result": "[]"} if method == "POST" else None)

	assert response.status_code == 404
