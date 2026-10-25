from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	model_config = SettingsConfigDict(env_file=".env", extra="ignore")

	app_name: str = Field(default="Bujo Digitizer", alias="APP_NAME")
	log_level: str = Field(default="INFO", alias="LOG_LEVEL")
	openai_api_key: str = Field(default="a", alias="OPENAI_API_KEY")
	openai_base_url: str = Field(alias="OPENAI_BASE_URL")
	ocr_model: str = Field(default="chandra-ocr-2", alias="OCR_MODEL")
	ocr_temperature: float = Field(default=0.5, ge=0.0, le=2.0, alias="OCR_TEMPERATURE")
	ocr_reasoning_budget_tokens: int = Field(default=3072, ge=0, alias="OCR_REASONING_BUDGET_TOKENS")
	parser_model: str = Field(default="qwen-3.8-27b", alias="PARSER_MODEL")
	parser_temperature: float = Field(default=0.6, ge=0.0, le=2.0, alias="PARSER_TEMPERATURE")
	parser_reasoning_budget_tokens: int = Field(default=256, ge=0, alias="PARSER_REASONING_BUDGET_TOKENS")
	paperless_base_url: str = Field(alias="PAPERLESS_BASE_URL")
	paperless_token: str = Field(alias="PAPERLESS_TOKEN")
	paperless_digitized_tag_id: int = Field(ge=1, alias="PAPERLESS_DIGITIZED_TAG_ID")
	sqlite_path: str = Field(default="./bujo_digitizer.sqlite3", alias="SQLITE_PATH")
	worker_poll_seconds: float = Field(default=2.0, alias="WORKER_POLL_SECONDS")
	worker_concurrency: int = Field(default=1, alias="WORKER_CONCURRENCY")
	worker_retry_interval_seconds: float = Field(default=3600, alias="WORKER_RETRY_INTERVAL_SECONDS")
	job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")

	obsidian_bujo_enabled: bool = Field(default=False, alias="OBSIDIAN_BUJO_ENABLED")
	obsidian_vault_path: str | None = Field(default=None, alias="OBSIDIAN_VAULT_PATH")
	obsidian_bujo_section: str = Field(default="Bujo", alias="OBSIDIAN_BUJO_SECTION")
	obsidian_note_template: str = Field(default="{year}/W{week:02d}/{date}.md", alias="OBSIDIAN_NOTE_TEMPLATE")


@lru_cache
def get_settings() -> Settings:
	return Settings()
