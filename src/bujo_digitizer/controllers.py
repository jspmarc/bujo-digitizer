import os
import re
import tempfile
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import ClassVar, TypedDict

import httpx2
from bs4 import BeautifulSoup, NavigableString, ResultSet, Tag
from openai import AsyncOpenAI

from bujo_digitizer.config import get_settings
from bujo_digitizer.exceptions import ObsidianControllerException, PaperlessControllerException
from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import (
	MARKERS_REVERSE,
	BujoEntry,
	BujoTimeGroup,
	BujoType,
	DigitizeRequest,
	DigitizeResponse,
	HealthResponse,
	ParserOutput,
)

logger = get_logger(__name__)


class PaperlessController:
	def __init__(self, base_url: str, token: str):
		self._base_url: str = base_url
		self._token: str = token
		self._client: httpx2.AsyncClient = httpx2.AsyncClient(timeout=30.0)

	def _get_headers(self) -> dict[str, str]:
		return {"Authorization": f"Token {self._token}"}

	async def aclose(self) -> None:
		await self._client.aclose()

	async def download_document(self, id: int) -> tuple[bytes, str | None]:
		doc_url = f"{self._base_url}/api/documents/{id}/download/"
		try:
			response = await self._client.get(doc_url, headers=self._get_headers())
			_ = response.raise_for_status()
		except httpx2.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {doc_url}."
			) from exc
		except httpx2.HTTPError as exc:
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
		except httpx2.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {patch_url}."
			) from exc
		except httpx2.HTTPError as exc:
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
		except httpx2.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {bulk_url}."
			) from exc
		except httpx2.HTTPError as exc:
			raise PaperlessControllerException("Failed to reach Paperless API") from exc

	async def get_created(self, id: int) -> str:
		"""The document's `created` date (YYYY-MM-DD), or an empty string when Paperless has none."""
		doc_url = f"{self._base_url}/api/documents/{id}/"
		try:
			response = await self._client.get(doc_url, headers=self._get_headers())
			_ = response.raise_for_status()
		except httpx2.HTTPStatusError as exc:
			raise PaperlessControllerException(
				f"Paperless API returned {exc.response.status_code} for {doc_url}."
			) from exc
		except httpx2.HTTPError as exc:
			raise PaperlessControllerException("Failed to reach Paperless API") from exc
		return str(response.json().get("created") or "")


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

			bs = BeautifulSoup(ocr_result, features="html.parser")
			page_boxes = bs.select("div[data-bbox]")
			ocr_results_with_bb.append(page_boxes)
			ocr_texts.append("\n".join(self._block_text(x) for x in page_boxes))
			logger.debug("OCR result cleaned: %s", ocr_texts[-1])

		content = [{"type": "input_image", "image_url": file_url} for file_url in request.file_urls]
		content.append({"type": "input_text", "text": "\n".join(ocr_texts)})
		response = await client.responses.parse(
			model="qwen-3.8-27b",
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


class ObsidianController:
	_HEADING_RE: ClassVar[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
	_FENCE_RE: ClassVar[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")
	_BUJO_TIME_RE: ClassVar[re.Pattern[str]] = re.compile(r"^(?:[01]\d|2[0-9]):[0-5]\d$")

	class _EntryDict(TypedDict):
		"""copies the shape of models.BujoEntry but allow mutations"""

		type: BujoType
		note: str
		sub_entries: list[ObsidianController._EntryDict]

	def __init__(self, enabled: bool = True, obsidian_path: str | None = None, section_name: str = "Bujo"):
		self._enabled: bool = enabled
		self._obsidian_path: str | None = obsidian_path
		self._section_name: str = section_name

		if self._enabled and self._obsidian_path is None:
			raise ValueError("Obsidian Bujo is enabled, but the path is not supplied.")
		elif not self._enabled:
			logger.info("Obsidian Bujo is disabled.")

	def _note_path(self, created: date) -> Path:
		week_created = created.isocalendar().week
		year_created = created.isocalendar().year
		return Path(self._obsidian_path or "") / str(year_created) / f"W{week_created:02d}" / f"{created:%Y-%m-%d}.md"

	def _locate_section(self, lines: list[str]) -> tuple[int, int]:
		"""Return (heading_idx, section_end) line indices for the configured section."""

		heading_idx: int = -1
		in_fence = False
		for i, line in enumerate(lines):
			if ObsidianController._FENCE_RE.match(line):
				in_fence = not in_fence
				continue
			if in_fence:
				continue

			matched = ObsidianController._HEADING_RE.match(line)
			if matched and matched.group(2).strip().casefold() == self._section_name.casefold():
				heading_idx = i
				break

		if heading_idx < 0:
			raise ObsidianControllerException(f"Section {self._section_name!r} not found.")

		section_end: int = len(lines)
		in_fence = False
		for i in range(heading_idx + 1, len(lines)):
			if ObsidianController._FENCE_RE.match(lines[i]):
				in_fence = not in_fence
				continue
			if in_fence:
				continue

			matched = ObsidianController._HEADING_RE.match(lines[i])
			# the whole surgical edit should only edit the content under one header and new
			# headers should be treated as the section_end
			if matched:
				section_end = i
				break

		return heading_idx, section_end

	@staticmethod
	def _parse_section(section_lines: list[str]) -> ParserOutput:
		"""Parse a Bujo section's lines back into a ParserOutput."""

		# entries are built as plain dicts first: BujoEntry is frozen, so nesting is assembled bottom-up
		groups: list[BujoTimeGroup] = []
		current_time = ""
		current_roots: list[ObsidianController._EntryDict] = []
		entry_stack: list[tuple[int, ObsidianController._EntryDict]] = []
		last_entry: ObsidianController._EntryDict | None = None

		def build(entry_dict: ObsidianController._EntryDict) -> BujoEntry:
			sub = entry_dict["sub_entries"]
			return BujoEntry(
				type=entry_dict["type"],
				note=entry_dict["note"],
				sub_entries=[build(child) for child in sub] if sub else None,
			)

		def _attach(entry_dict: ObsidianController._EntryDict, depth: int) -> None:
			# nest under the deepest entry shallower than `depth`, or make a new root
			while entry_stack and entry_stack[-1][0] >= depth:
				_ = entry_stack.pop()
			if entry_stack:
				entry_stack[-1][1]["sub_entries"].append(entry_dict)
			else:
				current_roots.append(entry_dict)
			entry_stack.append((depth, entry_dict))

		def flush() -> None:
			nonlocal current_time, current_roots, entry_stack, last_entry
			if current_time or current_roots:
				groups.append(
					BujoTimeGroup(time=current_time, bujos=[build(item) for item in current_roots]),
				)
			current_time, current_roots, entry_stack = "", [], []
			last_entry = None

		for raw in section_lines:
			stripped = raw.strip()
			if not stripped:
				# blank line separates time groups; a pending empty group keeps waiting for entries
				if current_roots:
					flush()
				continue

			if ObsidianController._BUJO_TIME_RE.fullmatch(stripped):
				flush()
				current_time = stripped
				continue

			indent = raw[: len(raw) - len(raw.lstrip())]
			depth = len(indent.expandtabs(4)) // 4

			entry_dict: ObsidianController._EntryDict
			body = stripped[2:] if stripped.startswith("- ") else None
			if body is not None and body[:1] in "([":
				marker = body[:3]
				# Obsidian also writes completed checkboxes as "[X]"
				entry_type = MARKERS_REVERSE.get(marker.casefold())
				if entry_type is not None:
					entry_dict = {"type": entry_type, "note": body[3:].strip(), "sub_entries": []}
					_attach(entry_dict, depth)
					last_entry = entry_dict
					continue
			if last_entry is not None and body is None:
				# a plain line after an entry is a wrapped continuation of its note
				last_entry["note"] = f"{last_entry['note']} {stripped}".strip()
				continue
			# unrecognized line: keep the content as a thought entry instead of merging it into a note
			logger.debug("Unrecognized Bujo line %r; treating as thought.", raw)
			note = stripped if body is None else body
			entry_dict = {"type": BujoType.THOUGHT, "note": note, "sub_entries": []}
			_attach(entry_dict, depth)
			last_entry = entry_dict

		flush()
		return ParserOutput(root=groups)

	def modify_obsidian(self, doc_created: str, content: ParserOutput) -> None:
		if not self._enabled:
			return

		if self._obsidian_path is None:
			raise ObsidianControllerException("Obsidian Bujo is enabled, but the path is not supplied.")

		try:
			created = date.fromisoformat(doc_created)
		except ValueError:
			raise ObsidianControllerException(
				f"Invalid created date {doc_created!r}; cannot locate the Obsidian note."
			) from None

		note_path = self._note_path(created)
		if not note_path.exists():
			raise ObsidianControllerException(f"Obsidian note {note_path} does not exist; create it and re-approve.")

		try:
			with note_path.open("r", encoding="utf-8") as f:
				md_content = f.read()
		except OSError as exc:
			raise ObsidianControllerException(f"Failed to read Obsidian note {note_path}: {exc}") from exc
		lines = md_content.splitlines()

		heading_idx, section_end = self._locate_section(lines)
		existing = self._parse_section(lines[heading_idx + 1 : section_end])
		merged = self._merge_section(existing, content)

		new_lines = lines[: heading_idx + 1]
		merged_md = merged.to_markdown()
		has_section_content = bool(merged_md)
		has_content_after = section_end < len(lines)
		if has_section_content:
			new_lines += ["", *merged_md.splitlines()]
		if has_section_content and has_content_after:
			# insert a blank line between the section and the following content so the
			# next heading (if any) does not sit directly under the last bullet
			new_lines.append("")
		new_lines += lines[section_end:]

		try:
			self._atomic_write(note_path, "\n".join(new_lines) + "\n")
		except OSError as exc:
			raise ObsidianControllerException(f"Failed to write Obsidian note {note_path}: {exc}") from exc

	@staticmethod
	def _atomic_write(note_path: Path, content: str) -> None:
		"""Replace the note via a sibling temp file so a crash or sync mid-write cannot truncate it."""
		tmp_name = ""
		try:
			with tempfile.NamedTemporaryFile(
				mode="w",
				encoding="utf-8",
				dir=note_path.parent,
				prefix=f".{note_path.name}.",
				suffix=".tmp",
				delete=False,
			) as tmp:
				tmp_name = tmp.name
				tmp.write(content)
				tmp.flush()
				os.fsync(tmp.fileno())
			os.replace(tmp_name, note_path)
		except OSError:
			if tmp_name:
				_ = Path(tmp_name).unlink(missing_ok=True)
			raise

	@staticmethod
	def _merge_section(existing: ParserOutput, new: ParserOutput) -> ParserOutput:
		combined: dict[str, list[BujoEntry]] = {}
		for time_group in [*existing.root, *new.root]:
			combined.setdefault(time_group.time, []).extend(time_group.bujos)
		for time, bujos in combined.items():
			combined[time] = list(dict.fromkeys(bujos))
		return ParserOutput(root=[BujoTimeGroup(time=time, bujos=bujos) for time, bujos in combined.items()])
