from enum import Enum

from pydantic import BaseModel, Field, RootModel


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
	image_url: str


class HealthResponse(BaseModel):
	status: str
