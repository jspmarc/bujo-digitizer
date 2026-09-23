import logging
from functools import lru_cache
from importlib import resources

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from bujo_digitizer.config import get_settings
from bujo_digitizer.models import (
	DigitizeRequest,
	DigitizeResponse,
	HealthResponse,
	ParserOutput,
)

logger = logging.getLogger(__name__)


class DigitizeController:
	def __init__(self):
		openai_client_settings = get_settings()
		self._client: AsyncOpenAI = AsyncOpenAI(
			api_key=openai_client_settings.openai_api_key,
			base_url=openai_client_settings.openai_base_url,
			max_retries=1,
		)

	@classmethod
	@lru_cache
	def __load_parser_prompt(cls) -> str:
		prompt = resources.files("bujo_digitizer").joinpath("prompts", "parser.md").read_text()
		json_format = resources.files("bujo_digitizer").joinpath("prompts", "parser_format.json").read_text()
		return prompt.replace("<###JSON_FORMAT###>", json_format)

	@classmethod
	@lru_cache
	def __load_ocr_prompt(cls) -> str:
		return resources.files("bujo_digitizer").joinpath("prompts", "ocr.md").read_text()

	async def digitize(self, request: DigitizeRequest) -> DigitizeResponse:
		client = self._client

		content = [
			{"type": "input_file", "file_url": request.file_url},
			{"type": "input_text", "text": self.__load_ocr_prompt()},
		]

		response = await client.responses.create(
			model="chandra-ocr-2",
			input=[{"role": "user", "content": content}],
			temperature=0.5,
			extra_body={"reasoning_budget_tokens": 3072},
		)
		ocr_result = "\n".join(
			part.text for item in response.output if item.type == "reasoning" and item.content for part in item.content
		)
		logger.debug("OCR LLM response: %s", ocr_result)

		bs = BeautifulSoup(ocr_result)
		ocr_result_with_bb_only = bs.select("div[data-bbox]")
		ocr_result = "\n".join([x.get_text() for x in ocr_result_with_bb_only])
		logger.debug("OCR Result cleaned: %s", ocr_result)

		content = [
			{"type": "input_file", "file_url": request.file_url},
			{"type": "input_text", "text": ocr_result},
		]
		response = await client.responses.parse(
			model="qwen-3.8-27b-vision",
			input=[
				{"role": "system", "content": self.__load_parser_prompt()},
				{"role": "user", "content": content},
			],
			reasoning={"effort": "low"},
			text_format=ParserOutput,
			timeout=60.0,
			temperature=0.6,
			top_p=0.95,
			extra_body={"reasoning_budget_tokens": 256},
		)
		logger.debug("Parser LLM raw response: %s", response.output_text)
		logger.debug("Parser LLM response: %s", response.output_parsed)
		parsed = (
			response.output_parsed.model_dump_json(ensure_ascii=True, indent=4)
			if response.output_parsed is not None
			else "null"
		)

		return DigitizeResponse(
			parser_output=response.output_parsed,
			ocr_result_with_bb=ocr_result_with_bb_only,
		)

	@staticmethod
	async def health() -> HealthResponse:
		return HealthResponse(status="ok")
