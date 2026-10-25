from functools import lru_cache
from importlib import resources

from bs4 import BeautifulSoup, NavigableString, ResultSet, Tag
from openai import AsyncOpenAI

from bujo_digitizer.config import get_settings
from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import DigitizeRequest, DigitizeResponse, HealthResponse, ParserOutput

logger = get_logger(__name__)


class DigitizeController:
	def __init__(self):
		openai_client_settings = get_settings()
		self._client: AsyncOpenAI = AsyncOpenAI(
			api_key=openai_client_settings.openai_api_key,
			base_url=openai_client_settings.openai_base_url,
			max_retries=1,
		)
		self._ocr_model: str = openai_client_settings.ocr_model
		self._ocr_temperature: float = openai_client_settings.ocr_temperature
		self._ocr_reasoning_budget_tokens: int = openai_client_settings.ocr_reasoning_budget_tokens
		self._parser_model: str = openai_client_settings.parser_model
		self._parser_temperature: float = openai_client_settings.parser_temperature
		self._parser_reasoning_budget_tokens: int = openai_client_settings.parser_reasoning_budget_tokens

	async def aclose(self) -> None:
		await self._client.close()

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

	@staticmethod
	def _block_text(div: Tag) -> str:
		parts: list[str] = []
		for child in div.descendants:
			if isinstance(child, NavigableString):
				parts.append(str(child))
			elif getattr(child, "name", None) == "br":
				parts.append("\n")
		return "".join(parts)

	async def digitize(self, request: DigitizeRequest) -> DigitizeResponse:
		client = self._client

		ocr_results_with_bb: list[ResultSet[Tag]] = []
		ocr_texts: list[str] = []

		for file_url in request.file_urls:
			content = [
				{"type": "input_image", "image_url": file_url},
				{"type": "input_text", "text": self.__load_ocr_prompt()},
			]

			response = await client.responses.create(
				model=self._ocr_model,
				input=[{"role": "user", "content": content}],
				temperature=self._ocr_temperature,
				extra_body={"reasoning_budget_tokens": self._ocr_reasoning_budget_tokens},
			)
			ocr_result = "\n".join(
				part.text
				for item in response.output
				if item.type == "reasoning" and item.content
				for part in item.content
			)
			logger.debug("OCR LLM response: %s", ocr_result)

			bs = BeautifulSoup(ocr_result, features="html.parser")
			page_boxes = bs.select("div[data-bbox]")
			ocr_results_with_bb.append(page_boxes)
			ocr_texts.append("\n".join(self._block_text(x) for x in page_boxes))
			logger.debug("OCR result cleaned: %s", ocr_texts[-1])

		content = [{"type": "input_image", "image_url": file_url} for file_url in request.file_urls]
		content.append({"type": "input_text", "text": "\n".join(ocr_texts)})
		response = await client.responses.parse(
			model=self._parser_model,
			input=[
				{"role": "system", "content": self.__load_parser_prompt()},
				{"role": "user", "content": content},
			],
			reasoning={"effort": "low"},
			text_format=ParserOutput,
			timeout=180.0,
			temperature=self._parser_temperature,
			top_p=0.95,
			extra_body={"reasoning_budget_tokens": self._parser_reasoning_budget_tokens},
		)
		logger.debug("Parser LLM raw response: %s", response.output_text)
		logger.debug("Parser LLM response: %s", response.output_parsed)

		return DigitizeResponse(
			parser_output=response.output_parsed,
			ocr_results_with_bb=ocr_results_with_bb,
		)

	@staticmethod
	async def health() -> HealthResponse:
		return HealthResponse(status="ok")
