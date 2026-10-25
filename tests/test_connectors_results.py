from collections.abc import Generator

import pytest

from bujo_digitizer.connectors import DigitizeResultStore


@pytest.fixture
def store(tmp_path) -> Generator[DigitizeResultStore]:
	result_store = DigitizeResultStore(str(tmp_path / "results.sqlite3"))
	result_store.initialize()
	yield result_store


def test_save_and_get_round_trip(store: DigitizeResultStore) -> None:
	result_id = store.save(42, "My document", "2026-01-05", '{"root": []}', "<div></div>", [b"page-1", b"page-2"])

	row = store.get(result_id)
	assert row is not None
	assert row["paperless_doc_id"] == 42
	assert row["doc_title"] == "My document"
	assert row["doc_created"] == "2026-01-05"
	assert row["parse_result"] == '{"root": []}'
	assert row["bbox_elements"] == "<div></div>"


def test_list_all_returns_newest_first(store: DigitizeResultStore) -> None:
	first = store.save(1, "First", "", None, "[]", [])
	second = store.save(2, "Second", "", None, "[]", [])

	assert [row["id"] for row in store.list_all()] == [second, first]


def test_get_missing_row_returns_none(store: DigitizeResultStore) -> None:
	assert store.get(999) is None


def test_page_count_and_get_page(store: DigitizeResultStore) -> None:
	result_id = store.save(1, "Doc", "", None, "[]", [b"first", b"second"])

	assert store.page_count(result_id) == 2
	assert store.get_page(result_id, 0) == b"first"
	assert store.get_page(result_id, 1) == b"second"
	assert store.get_page(result_id, 2) is None


def test_delete_removes_result_and_pages(store: DigitizeResultStore) -> None:
	result_id = store.save(1, "Doc", "", None, "[]", [b"page"])

	store.delete(result_id)

	assert store.get(result_id) is None
	assert store.page_count(result_id) == 0


def test_initialize_is_idempotent(tmp_path) -> None:
	path = str(tmp_path / "idempotent.sqlite3")
	first = DigitizeResultStore(path)
	first.initialize()
	_ = first.save(1, "Doc", "", None, "[]", [])

	second = DigitizeResultStore(path)
	second.initialize()

	assert second.list_all()[0]["doc_title"] == "Doc"
