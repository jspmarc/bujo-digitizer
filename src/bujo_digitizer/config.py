import os

from pydantic import BaseModel


class Settings(BaseModel):
    openai_api_key: str = "a"
    openai_base_url: str | None = None


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.environ.get("BUJO_DIGITIZER_OPENAI_API_KEY", "a"),
        openai_base_url=os.environ.get("BUJO_DIGITIZER_OPENAI_BASE_URL", "https://llm.box.jspmarc.dev"),
    )
