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
def _load_parser_prompt() -> str:
    prompt = resources.files("bujo_digitizer").joinpath("prompts", "parser.md").read_text()
    json_format = resources.files("bujo_digitizer").joinpath("prompts", "parser_format.json").read_text()
    return prompt.replace("<###JSON_FORMAT###>", json_format)


@lru_cache
def _load_ocr_prompt() -> str:
    return resources.files("bujo_digitizer").joinpath("prompts", "ocr.md").read_text()


class DigitizeController:
    def __init__(self):
        openai_client_settings = get_settings()
        self._client: AsyncOpenAI = AsyncOpenAI(
            api_key=openai_client_settings.openai_api_key,
            base_url=openai_client_settings.openai_base_url,
            max_retries=1,
        )

    async def digitize(self, request: DigitizeRequest) -> DigitizeResponse:
        client = self._client

        content = [
            {"type": "input_image", "image_url": request.image_url},
            {"type": "input_text", "text": _load_ocr_prompt()},
        ]

        response = await client.responses.create(
            model="chandra-ocr-2",
            input=[{"role": "user", "content": content}],
            temperature=0.2,
            extra_body={"reasoning_budget_tokens": 3072},
        )

        ocr_result = "\n".join(
            part.text for item in response.output if item.type == "reasoning" and item.content for part in item.content
        )
        logger.debug("OCR LLM response: %s", ocr_result)
        content = [
            {"type": "input_image", "image_url": request.image_url},
            {"type": "input_text", "text": ocr_result},
        ]
        response = await client.responses.parse(
            model="qwen-3.8-27b-vision",
            input=[
                {"role": "system", "content": _load_parser_prompt()},
                {"role": "user", "content": content},
            ],
            reasoning={"effort": "low"},
            text_format=ParserOutput,
            timeout=120.0,
            temperature=0.2,
            extra_body={"reasoning_budget_tokens": 1024},
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
