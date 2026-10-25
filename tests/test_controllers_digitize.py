from typing import Any

import pytest

from bujo_digitizer.controllers import DigitizeController
from bujo_digitizer.models import BujoTimeGroup, DigitizeRequest, ParserOutput


class _TextPart:
	def __init__(self, text: str) -> None:
		self.text = text


class _ReasoningItem:
	type = "reasoning"

	def __init__(self, text: str) -> None:
		self.content = [_TextPart(text)]


class _CreateResponse:
	def __init__(self, text: str) -> None:
		self.output = [_ReasoningItem(text)]


class _ParseResponse:
	def __init__(self, parsed: ParserOutput) -> None:
		self.output_text = "raw parser output"
		self.output_parsed = parsed


class _Responses:
	def __init__(self, ocr_html: str, parsed: ParserOutput) -> None:
		self.ocr_html = ocr_html
		self.parsed = parsed
		self.create_calls: list[dict[str, Any]] = []
		self.parse_calls: list[dict[str, Any]] = []

	async def create(self, **kwargs: Any) -> _CreateResponse:
		self.create_calls.append(kwargs)
		return _CreateResponse(self.ocr_html)

	async def parse(self, **kwargs: Any) -> _ParseResponse:
		self.parse_calls.append(kwargs)
		return _ParseResponse(self.parsed)


class _FakeOpenAI:
	def __init__(self, responses: _Responses) -> None:
		self.responses = responses
		self.closed = False

	async def close(self) -> None:
		self.closed = True


@pytest.mark.anyio
async def test_health_reports_ok() -> None:
	controller = DigitizeController()
	try:
		response = await controller.health()
	finally:
		await controller.aclose()

	assert response.status == "ok"


@pytest.mark.anyio
async def test_digitize_runs_ocr_per_page_then_parses() -> None:
	parsed = ParserOutput(root=[BujoTimeGroup(time="09:00", bujos=[])])
	responses = _Responses('<div data-bbox="0 0 10 10">Hello<br>world</div>', parsed)
	fake = _FakeOpenAI(responses)

	controller = DigitizeController()
	await controller.aclose()
	controller._client = fake
	try:
		result = await controller.digitize(
			DigitizeRequest(file_urls=["data:image/jpeg;base64,AAA", "data:image/jpeg;base64,BBB"])
		)
	finally:
		await controller.aclose()

	assert result.parser_output == parsed
	assert len(result.ocr_results_with_bb) == 2
	assert all(len(page) == 1 for page in result.ocr_results_with_bb)
	assert len(responses.create_calls) == 2
	assert len(responses.parse_calls) == 1
	parser_user_content = responses.parse_calls[0]["input"][1]["content"]
	assert parser_user_content[-1] == {"type": "input_text", "text": "Hello\nworld\nHello\nworld"}
	assert fake.closed is True


@pytest.mark.anyio
async def test_aclose_closes_the_openai_client() -> None:
	fake = _FakeOpenAI(_Responses("", ParserOutput(root=[])))
	controller = DigitizeController()
	await controller.aclose()
	controller._client = fake

	await controller.aclose()

	assert fake.closed is True
