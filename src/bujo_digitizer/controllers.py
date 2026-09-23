import logging
from functools import lru_cache
from importlib import resources

import httpx
from bs4 import BeautifulSoup, NavigableString, ResultSet, Tag
from openai import AsyncOpenAI

from bujo_digitizer.config import get_settings
from bujo_digitizer.exceptions import PaperlessControllerException
from bujo_digitizer.models import (
	DigitizeRequest,
	DigitizeResponse,
	HealthResponse,
	ParserOutput,
)

logger = logging.getLogger(__name__)


def _block_text(div: Tag) -> str:
	parts: list[str] = []
	for child in div.descendants:
		if isinstance(child, NavigableString):
			parts.append(str(child))
		elif getattr(child, "name", None) == "br":
			parts.append("\n")
	return "".join(parts)


class PaperlessController:
	def __init__(self, base_url: str, token: str):
		self._base_url: str = base_url
		self._token: str = token
		self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)

	def _get_headers(self) -> dict[str, str]:
		return {"Authorization": f"Token {self._token}"}

	async def aclose(self) -> None:
		await self._client.aclose()

	async def download_document(self, id: int) -> tuple[bytes, str | None]:
		doc_url = f"{self._base_url}/api/documents/{id}/download/"
		try:
			response = await self._client.get(doc_url, headers=self._get_headers())
			_ = response.raise_for_status()
		except httpx.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {doc_url}."
			) from exc
		except httpx.HTTPError as exc:
			raise PaperlessControllerException("Failed to reach Paperless API") from exc
		return response.content, response.headers.get("content-type")

	async def update_document_content(self, id: int, content: str) -> None:
		patch_url = f"{self._base_url}/api/documents/{id}/"
		request_body = {
			"content": content,
		}
		try:
			response = await self._client.patch(
				patch_url,
				json=request_body,
				headers=self._get_headers(),
			)
			_ = response.raise_for_status()
		except httpx.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {patch_url}."
			) from exc
		except httpx.HTTPError as exc:
			raise PaperlessControllerException("Failed to reach Paperless API") from exc

	async def add_document_tag(self, id: int, tag_id: int) -> None:
		bulk_url = f"{self._base_url}/api/documents/bulk_edit/"
		request_body = {
			"documents": [id],
			"method": "add_tag",
			"parameters": {"tag": tag_id},
		}
		try:
			response = await self._client.post(
				bulk_url,
				json=request_body,
				headers=self._get_headers(),
			)
			_ = response.raise_for_status()
		except httpx.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {bulk_url}."
			) from exc
		except httpx.HTTPError as exc:
			raise PaperlessControllerException("Failed to reach Paperless API") from exc


class DigitizeController:
	def __init__(self):
		openai_client_settings = get_settings()
		self._client: AsyncOpenAI = AsyncOpenAI(
			api_key=openai_client_settings.openai_api_key,
			base_url=openai_client_settings.openai_base_url,
			max_retries=1,
		)

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
				model="chandra-ocr-2",
				input=[{"role": "user", "content": content}],
				temperature=0.5,
				extra_body={"reasoning_budget_tokens": 3072},
			)
			ocr_result = "\n".join(
				part.text
				for item in response.output
				if item.type == "reasoning" and item.content
				for part in item.content
			)
			logger.debug("OCR LLM response: %s", ocr_result)

			bs = BeautifulSoup(ocr_result)
			page_boxes = bs.select("div[data-bbox]")
			ocr_results_with_bb.append(page_boxes)
			ocr_texts.append("\n".join(_block_text(x) for x in page_boxes))
			logger.debug("OCR result cleaned: %s", ocr_texts[-1])

		content = [{"type": "input_image", "image_url": file_url} for file_url in request.file_urls]
		content.append({"type": "input_text", "text": "\n".join(ocr_texts)})
		response = await client.responses.parse(
			model="qwen-3.8-27b-vision",
			input=[
				{"role": "system", "content": self.__load_parser_prompt()},
				{"role": "user", "content": content},
			],
			reasoning={"effort": "low"},
			text_format=ParserOutput,
			timeout=180.0,
			temperature=0.6,
			top_p=0.95,
			extra_body={"reasoning_budget_tokens": 256},
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
