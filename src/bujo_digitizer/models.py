from datetime import date
from enum import Enum

from bs4 import ResultSet, Tag
from pydantic import BaseModel, ConfigDict, Field, RootModel


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
_MARKERS_REVERSE: dict[str, BujoType] = {v: k for k, v in _MARKERS.items()}


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

	def to_dict(self) -> dict[str, list[BujoEntry]]:
		return {time_group.time: time_group.bujos for time_group in self.root}


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
	created: date
