import logging
from functools import lru_cache
from importlib import resources

from openai import AsyncOpenAI

from bujo_digitizer.config import get_settings
from bujo_digitizer.models import (
    DigitizeRequest,
    DigitizeResponse,
    HealthResponse,
    ParserOutput,
)

logger = logging.getLogger(__name__)


@lru_cache
def _openai_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


@lru_cache
def _load_parser_prompt() -> str:
    prompt = (
        resources.files("bujo_digitizer").joinpath("prompts", "parser.md").read_text()
    )
    json_format = (
        resources.files("bujo_digitizer")
        .joinpath("prompts", "parser_format.json")
        .read_text()
    )
    return prompt.replace("<###JSON_FORMAT###>", json_format)


class DigitizeController:
    @staticmethod
    async def digitize(request: DigitizeRequest) -> DigitizeResponse:
        client = _openai_client()

        content = [
            {"type": "input_image", "image_url": request.image_url},
            {"type": "input_text", "text": "ocr"},
        ]

        response = await client.responses.create(
            model="paddleocr-vl-1.6",
            input=[{"role": "user", "content": content}],
            temperature=0.0,
        )

        ocr_result = response.output_text
        logger.debug("OCR LLM response: %s", ocr_result)
        content = [
            {"type": "input_image", "image_url": request.image_url},
            {"type": "input_text", "text": ocr_result},
        ]
        response = await client.responses.parse(
            model="qwen-3.5-9b",
            input=[
                {"role": "system", "content": _load_parser_prompt()},
                {"role": "user", "content": content},
            ],
            text_format=ParserOutput,
        )
        logger.debug("Parser LLM raw response: %s", response.output_text)
        logger.debug("Parser LLM response: %s", response.output_parsed)

        return DigitizeResponse(
            id=response.id,
            content=response.output_parsed,
        )

    @staticmethod
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")
