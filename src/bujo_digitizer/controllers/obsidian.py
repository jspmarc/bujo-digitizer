import os
import re
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TypedDict

from bujo_digitizer.logger import get_logger
from bujo_digitizer.models import MARKERS_REVERSE, BujoEntry, BujoTimeGroup, BujoType, ParserOutput

logger = get_logger(__name__)

_HEADING_RE: re.Pattern[str] = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE: re.Pattern[str] = re.compile(r"^\s*(```|~~~)")
_BUJO_TIME_RE: re.Pattern[str] = re.compile(r"^(?:[01]\d|2[0-9]):[0-5]\d$")


class _EntryDict(TypedDict):
	"""copies the shape of models.BujoEntry but allow mutations"""

	type: BujoType
	note: str
	sub_entries: list[_EntryDict]


class ObsidianControllerException(Exception):
	"""Raised when an Obsidian note update fails (missing note/section, invalid date, IO error)."""


class ObsidianController:
	def __init__(
		self,
		enabled: bool = True,
		obsidian_path: str | None = None,
		section_name: str = "Bujo",
		note_template: str = "{year}/W{week:02d}/{date}.md",
	):
		self._enabled: bool = enabled
		self._obsidian_path: str | None = obsidian_path
		self._section_name: str = section_name
		self._note_template: str = note_template
		# modify_obsidian runs in a worker thread; serialize read-modify-write per note
		self._note_locks: dict[Path, threading.Lock] = {}
		self._note_locks_guard: threading.Lock = threading.Lock()

		if self._enabled and not self._obsidian_path:
			raise ValueError("Obsidian Bujo is enabled, but the path is not supplied.")
		elif not self._enabled:
			logger.info("Obsidian Bujo is disabled.")

	def _lock_for(self, note_path: Path) -> threading.Lock:
		with self._note_locks_guard:
			return self._note_locks.setdefault(note_path, threading.Lock())

	def _note_path(self, created: date) -> Path:
		iso = created.isocalendar()
		rel = self._note_template.format(year=iso.year, week=iso.week, date=created)
		return Path(self._obsidian_path or "") / rel

	def _locate_section(self, lines: list[str]) -> tuple[int, int]:
		"""Return (heading_idx, section_end) line indices for the configured section."""

		heading_idx: int = -1
		in_fence = False
		for i, line in enumerate(lines):
			if _FENCE_RE.match(line):
				in_fence = not in_fence
				continue
			if in_fence:
				continue

			matched = _HEADING_RE.match(line)
			if matched and matched.group(2).strip().casefold() == self._section_name.casefold():
				heading_idx = i
				break

		if heading_idx < 0:
			raise ObsidianControllerException(f"Section {self._section_name!r} not found.")

		section_end: int = len(lines)
		in_fence = False
		for i in range(heading_idx + 1, len(lines)):
			if _FENCE_RE.match(lines[i]):
				in_fence = not in_fence
				continue
			if in_fence:
				continue

			matched = _HEADING_RE.match(lines[i])
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
		current_roots: list[_EntryDict] = []
		entry_stack: list[tuple[int, _EntryDict]] = []
		last_entry: _EntryDict | None = None

		def build(entry_dict: _EntryDict) -> BujoEntry:
			sub = entry_dict["sub_entries"]
			return BujoEntry(
				type=entry_dict["type"],
				note=entry_dict["note"],
				sub_entries=[build(child) for child in sub] if sub else None,
			)

		def _attach(entry_dict: _EntryDict, depth: int) -> None:
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

			if _BUJO_TIME_RE.fullmatch(stripped):
				flush()
				current_time = stripped
				continue

			indent = raw[: len(raw) - len(raw.lstrip())]
			# 2-space, 4-space and tab indentation all count as one nesting level; `_attach` only
			# compares relative depths, so the generated tab indent (4 cols) still nests correctly
			depth = len(indent.expandtabs(4)) // 2

			entry_dict: _EntryDict
			body = stripped[2:] if stripped[:2] in ("- ", "* ", "+ ") else None
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

	@staticmethod
	def _parse_created(doc_created: str) -> date:
		"""Accept a plain ISO date or a full ISO datetime (Paperless reports `created` as a datetime)."""
		try:
			return date.fromisoformat(doc_created)
		except ValueError:
			pass
		try:
			return datetime.fromisoformat(doc_created).date()
		except ValueError:
			raise ObsidianControllerException(
				f"Invalid created date {doc_created!r}; cannot locate the Obsidian note."
			) from None

	def modify_obsidian(self, doc_created: str, content: ParserOutput) -> None:
		if not self._enabled:
			return

		if not self._obsidian_path:
			raise ObsidianControllerException("Obsidian Bujo is enabled, but the path is not supplied.")

		created = self._parse_created(doc_created)
		note_path = self._note_path(created)

		with self._lock_for(note_path):
			if not note_path.exists():
				raise ObsidianControllerException(
					f"Obsidian note {note_path} does not exist; create it and re-approve."
				)

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
			# NamedTemporaryFile creates the file 0600; preserve the note's original mode
			os.chmod(tmp_name, note_path.stat().st_mode)
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
			# BujoEntry is frozen but hashless (identity-based), so dict.fromkeys won't dedupe;
			# dedupe on the serialized JSON form which captures all fields recursively
			unique: list[BujoEntry] = []
			seen: set[str] = set()
			for entry in bujos:
				key = entry.model_dump_json()
				if key not in seen:
					seen.add(key)
					unique.append(entry)
			combined[time] = unique
		return ParserOutput(root=[BujoTimeGroup(time=time, bujos=bujos) for time, bujos in sorted(combined.items())])
