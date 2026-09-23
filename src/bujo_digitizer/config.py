from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	model_config = SettingsConfigDict(env_file=".env", extra="ignore")

	app_name: str = Field(default="Bujo Digitizer", alias="APP_NAME")
	log_level: str = Field(default="INFO", alias="LOG_LEVEL")
	openai_api_key: str = Field(default="a", alias="OPENAI_API_KEY")
	openai_base_url: str = Field(alias="OPENAI_BASE_URL")
	paperless_base_url: str = Field(alias="PAPERLESS_BASE_URL")
	paperless_token: str = Field(alias="PAPERLESS_TOKEN")
	sqlite_path: str = Field(default="./bujo_digitizer.sqlite3", alias="SQLITE_PATH")
	worker_poll_seconds: float = Field(default=2.0, alias="WORKER_POLL_SECONDS")
	worker_concurrency: int = Field(default=1, alias="WORKER_CONCURRENCY")
	job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")


@lru_cache
def get_settings() -> Settings:
	return Settings()
