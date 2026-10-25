from datetime import date
from enum import Enum
from typing import override

from bs4 import ResultSet, Tag
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class BujoType(str, Enum):
	THOUGHT = "THOUGHT"
	FEELING = "FEELING"
	EVENT = "EVENT"
	PENDING_TASK = "PENDING_TASK"
	FINISHED_TASK = "FINISHED_TASK"
	CANCELLED_TASK = "CANCELLED_TASK"
	FUTURE_TASK = "FUTURE_TASK"
	OBSIDIAN_TASK = "OBSIDIAN_TASK"


class BujoEntry(BaseModel):
	model_config = ConfigDict(frozen=True)

	type: BujoType
	note: str
	sub_entries: list[BujoEntry] | None = None

	@field_validator("sub_entries", mode="after")
	@classmethod
	def _none_if_empty(cls, value: list[BujoEntry] | None) -> list[BujoEntry] | None:
		# if value is empty, then return None
		return value or None

	@override
	def __hash__(self) -> int:
		# frozen's auto __hash__ can't handle the list field; JSON captures all fields recursively
		return hash(self.model_dump_json())


class BujoTimeGroup(BaseModel):
	time: str = Field(pattern=r"^$|([01]\d|2[0-9]):[0-5]\d$")
	bujos: list[BujoEntry]


_MARKERS: dict[BujoType, str] = {
	BujoType.THOUGHT: "(T)",
	BujoType.FEELING: "(F)",
	BujoType.EVENT: "(E)",
	BujoType.PENDING_TASK: "[ ]",
	BujoType.CANCELLED_TASK: "[-]",
	BujoType.FINISHED_TASK: "[x]",
	BujoType.FUTURE_TASK: "[>]",
	BujoType.OBSIDIAN_TASK: "[<]",
}
MARKERS_REVERSE: dict[str, BujoType] = {v.casefold(): k for k, v in _MARKERS.items()}


def _format_entries(entries: list[BujoEntry], depth: int = 0) -> list[str]:
	lines = []
	for entry in entries:
		indent = "\t" * depth
		lines.append(f"{indent}- {_MARKERS[entry.type]} {entry.note}")
		lines += _format_entries(entry.sub_entries or [], depth + 1)
	return lines


class ParserOutput(RootModel[list[BujoTimeGroup]]):
	def to_markdown(self) -> str:
		groups = []
		for group in self.root:
			lines = [group.time] if group.time else []
			lines += _format_entries(group.bujos)
			groups.append("\n".join(lines))
		return "\n\n".join(groups)


class DigitizeRequest(BaseModel):
	file_urls: list[str]


class DigitizeResponse(BaseModel):
	model_config = ConfigDict(arbitrary_types_allowed=True)

	parser_output: ParserOutput | None
	ocr_results_with_bb: list[ResultSet[Tag]]


class HealthResponse(BaseModel):
	status: str


class PaperlessWebhookPayload(BaseModel):
	doc_id: int
	doc_title: str
	# optional so webhook templates without it keep working; Obsidian updates are skipped when absent
	created: date | None = None

	@field_validator("created", mode="before")
	@classmethod
	def _date_only(cls, value: object) -> object:
		# Paperless may format `created` as a full ISO datetime; only the date part is needed
		if isinstance(value, str) and len(value) > 10:
			return value[:10]
		return value
