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
	type: BujoType
	note: str


class BujoTimeGroup(BaseModel):
	time: str = Field(pattern=r"^$|([01]\d|2[0-9]):[0-5]\d$")
	bujos: list[BujoEntry]


class ParserOutput(RootModel[list[BujoTimeGroup]]):
	pass


class DigitizeRequest(BaseModel):
	file_url: str


class DigitizeResponse(BaseModel):
	model_config = ConfigDict(arbitrary_types_allowed=True)

	parser_output: ParserOutput | None
	ocr_result_with_bb: ResultSet[Tag]


class HealthResponse(BaseModel):
	status: str


class PaperlessWebhookPayload(BaseModel):
	doc_id: int
