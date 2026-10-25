from datetime import date

import pytest

from bujo_digitizer.controllers import ObsidianController, ObsidianControllerException
from bujo_digitizer.models import BujoEntry, BujoTimeGroup, BujoType, ParserOutput


def _content(note: str = "new thought") -> ParserOutput:
	return ParserOutput(
		root=[
			BujoTimeGroup(
				time="09:00",
				bujos=[BujoEntry(type=BujoType.THOUGHT, note=note)],
			)
		]
	)


def _controller(vault) -> ObsidianController:
	return ObsidianController(
		enabled=True,
		obsidian_path=str(vault),
		note_template="{date}.md",
	)


def _note_for(vault, day: date):
	return vault / f"{day.isoformat()}.md"


def test_modify_obsidian_merges_into_the_bujo_section(tmp_path) -> None:
	day = date(2026, 1, 5)
	note = _note_for(tmp_path, day)
	note.write_text("# Bujo\n- (T) existing\n\n## Journal\nkeep me\n", encoding="utf-8")

	_controller(tmp_path).modify_obsidian(day.isoformat(), _content())

	written = note.read_text(encoding="utf-8")
	assert "- (T) existing" in written
	assert "- (T) new thought" in written
	assert "## Journal\nkeep me" in written


def test_modify_obsidian_accepts_a_full_datetime(tmp_path) -> None:
	day = date(2026, 1, 5)
	note = _note_for(tmp_path, day)
	note.write_text("# Bujo\n", encoding="utf-8")

	_controller(tmp_path).modify_obsidian("2026-01-05T12:34:56Z", _content())

	assert "- (T) new thought" in note.read_text(encoding="utf-8")


def test_modify_obsidian_is_idempotent(tmp_path) -> None:
	day = date(2026, 1, 5)
	note = _note_for(tmp_path, day)
	note.write_text("# Bujo\n", encoding="utf-8")
	controller = _controller(tmp_path)

	controller.modify_obsidian(day.isoformat(), _content())
	controller.modify_obsidian(day.isoformat(), _content())

	assert note.read_text(encoding="utf-8").count("- (T) new thought") == 1


def test_modify_obsidian_preserves_nested_entries(tmp_path) -> None:
	day = date(2026, 1, 5)
	note = _note_for(tmp_path, day)
	note.write_text("# Bujo\n\n09:00\n- (T) parent\n\t- [ ] child\n", encoding="utf-8")

	_controller(tmp_path).modify_obsidian(day.isoformat(), _content("another"))

	written = note.read_text(encoding="utf-8")
	assert "- (T) parent" in written
	assert "\t- [ ] child" in written
	assert "- (T) another" in written


def test_modify_obsidian_is_a_noop_when_disabled(tmp_path) -> None:
	controller = ObsidianController(enabled=False)

	controller.modify_obsidian("2026-01-05", _content())

	assert list(tmp_path.iterdir()) == []


def test_enabled_controller_requires_a_path() -> None:
	with pytest.raises(ValueError, match="path is not supplied"):
		ObsidianController(enabled=True)


def test_modify_obsidian_requires_an_existing_note(tmp_path) -> None:
	with pytest.raises(ObsidianControllerException, match="does not exist"):
		_controller(tmp_path).modify_obsidian("2026-01-05", _content())


def test_modify_obsidian_requires_the_section(tmp_path) -> None:
	note = _note_for(tmp_path, date(2026, 1, 5))
	note.write_text("# Other\n", encoding="utf-8")

	with pytest.raises(ObsidianControllerException, match="not found"):
		_controller(tmp_path).modify_obsidian("2026-01-05", _content())


def test_modify_obsidian_rejects_an_invalid_date(tmp_path) -> None:
	with pytest.raises(ObsidianControllerException, match="Invalid created date"):
		_controller(tmp_path).modify_obsidian("not-a-date", _content())
