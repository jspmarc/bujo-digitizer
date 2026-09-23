from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	model_config = SettingsConfigDict(env_file=".env", extra="ignore")

	openai_api_key: str = Field(default="a", alias="OPENAI_API_KEY")
	openai_base_url: str = Field(alias="OPENAI_BASE_URL")
	paperless_base_url: str = Field(alias="PAPERLESS_BASE_URL")
	paperless_token: str = Field(alias="PAPERLESS_TOKEN")
	sqlite_path: str = Field(default="./bujo_digitizer.sqlite3", alias="SQLITE_PATH")


@lru_cache
def get_settings() -> Settings:
	return Settings()
