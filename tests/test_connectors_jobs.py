from collections.abc import Generator

import pytest

from bujo_digitizer.connectors import (
	JOB_STATUS_DONE,
	JOB_STATUS_FAILED,
	JOB_STATUS_PENDING,
	JOB_STATUS_RUNNING,
	DigitizeJobStore,
)


@pytest.fixture
def jobs(tmp_path) -> Generator[DigitizeJobStore]:
	job_store = DigitizeJobStore(str(tmp_path / "jobs.sqlite3"))
	job_store.initialize()
	yield job_store


def test_enqueue_returns_an_id_and_lists_pending(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "2026-01-05")

	job = jobs.get(job_id)
	assert job is not None
	assert job["status"] == JOB_STATUS_PENDING
	assert job["attempts"] == 0
	assert [row["id"] for row in jobs.list_jobs()] == [job_id]


def test_enqueue_deduplicates_active_jobs(jobs: DigitizeJobStore) -> None:
	first = jobs.enqueue(7, "Doc", "")
	second = jobs.enqueue(7, "Doc", "")

	assert first == second


def test_enqueue_allows_a_new_job_after_the_previous_one_is_done(jobs: DigitizeJobStore) -> None:
	first = jobs.enqueue(7, "Doc", "")
	jobs.claim_next()
	jobs.complete(first)

	second = jobs.enqueue(7, "Doc", "")

	assert second != first


def test_claim_next_marks_the_job_running_and_counts_an_attempt(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "")

	claimed = jobs.claim_next()

	assert claimed is not None
	assert claimed["id"] == job_id
	assert claimed["status"] == JOB_STATUS_RUNNING
	assert claimed["attempts"] == 1
	assert jobs.claim_next() is None


def test_complete_closes_a_job(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "")
	jobs.claim_next()

	jobs.complete(job_id)

	job = jobs.get(job_id)
	assert job is not None
	assert job["status"] == JOB_STATUS_DONE
	assert job["last_error"] is None


def test_fail_requeues_until_attempts_are_exhausted(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "", max_attempts=2)

	jobs.claim_next()
	jobs.fail(job_id, "first failure")
	assert jobs.get(job_id)["status"] == JOB_STATUS_PENDING

	jobs.claim_next()
	jobs.fail(job_id, "second failure")
	job = jobs.get(job_id)
	assert job is not None
	assert job["status"] == JOB_STATUS_FAILED
	assert job["last_error"] == "second failure"


def test_requeue_running_resets_in_flight_jobs(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "")
	jobs.claim_next()

	reclaimed = jobs.requeue_running()

	assert reclaimed == 1
	assert jobs.get(job_id)["status"] == JOB_STATUS_PENDING


def test_retry_failed_requeues_failed_jobs(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(job_id, "boom")

	retried = jobs.retry_failed()

	assert retried == 1
	job = jobs.get(job_id)
	assert job["status"] == JOB_STATUS_PENDING
	assert job["last_error"] is None


def test_retry_failed_skips_documents_with_an_active_job(jobs: DigitizeJobStore) -> None:
	failed_id = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(failed_id, "boom")
	# a redelivered webhook queues a fresh job while the failed one still exists
	active_id = jobs.enqueue(7, "Doc", "")

	assert jobs.retry_failed() == 0
	assert jobs.get(failed_id)["status"] == JOB_STATUS_FAILED
	assert jobs.get(active_id)["status"] == JOB_STATUS_PENDING


def test_retry_failed_requeues_one_job_per_document(jobs: DigitizeJobStore) -> None:
	first = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(first, "boom")
	second = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(second, "boom again")

	assert jobs.retry_failed() == 1
	statuses = {jobs.get(first)["status"], jobs.get(second)["status"]}
	assert statuses == {JOB_STATUS_PENDING, JOB_STATUS_FAILED}
	assert jobs.get(second)["status"] == JOB_STATUS_PENDING


def test_retry_failed_skips_older_attempts_after_the_newest_job_succeeds(jobs: DigitizeJobStore) -> None:
	first = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(first, "boom")
	second = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(second, "boom again")

	assert jobs.retry_failed() == 1
	claimed = jobs.claim_next()
	assert claimed is not None
	jobs.complete(claimed["id"])

	assert jobs.retry_failed() == 0
	assert jobs.get(first)["status"] == JOB_STATUS_FAILED
	assert jobs.get(second)["status"] == JOB_STATUS_DONE


def test_retry_refuses_when_the_document_has_an_active_job(jobs: DigitizeJobStore) -> None:
	failed_id = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(failed_id, "boom")
	_ = jobs.enqueue(7, "Doc", "")

	assert jobs.retry(failed_id) is False
	assert jobs.get(failed_id)["status"] == JOB_STATUS_FAILED


def test_retry_resets_attempts_for_a_failed_job(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "", max_attempts=1)
	jobs.claim_next()
	jobs.fail(job_id, "boom")

	assert jobs.retry(job_id) is True

	job = jobs.get(job_id)
	assert job["status"] == JOB_STATUS_PENDING
	assert job["attempts"] == 0
	assert job["last_error"] is None
	assert jobs.retry(job_id) is False


def test_delete_removes_the_job(jobs: DigitizeJobStore) -> None:
	job_id = jobs.enqueue(7, "Doc", "")

	assert jobs.delete(job_id) is True
	assert jobs.get(job_id) is None
	assert jobs.delete(job_id) is False


def test_list_jobs_only_returns_attention_statuses(jobs: DigitizeJobStore) -> None:
	done_id = jobs.enqueue(1, "Done", "")
	jobs.claim_next()
	jobs.complete(done_id)
	pending_id = jobs.enqueue(2, "Pending", "")

	assert [row["id"] for row in jobs.list_jobs()] == [pending_id]
	assert [row["id"] for row in jobs.list_jobs(statuses=(JOB_STATUS_DONE,))] == [done_id]
