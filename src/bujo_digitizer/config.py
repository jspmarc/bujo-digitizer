import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
	openai_api_key: str = "a"
	openai_base_url: str
	paperless_base_url: str
	paperless_token: str


@lru_cache
def get_settings() -> Settings:
	return Settings(
		openai_api_key=os.environ.get("OPENAI_API_KEY", "a"),
		openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://llm.box.jspmarc.dev"),
		paperless_base_url=os.environ["PAPERLESS_BASE_URL"],
		paperless_token=os.environ["PAPERLESS_TOKEN"],
	)
