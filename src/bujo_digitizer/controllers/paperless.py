from datetime import datetime

import httpx2

from bujo_digitizer.logger import get_logger

logger = get_logger(__name__)


class PaperlessControllerException(Exception):
	"""Raised when the Paperless API cannot be reached or rejects a request."""


class PaperlessController:
	def __init__(self, base_url: str, token: str):
		self._base_url: str = base_url
		self._token: str = token
		self._client: httpx2.AsyncClient = httpx2.AsyncClient(timeout=30.0)

	@staticmethod
	def _date_only(value: object) -> str:
		"""Normalize a Paperless date/datetime value to an ISO `YYYY-MM-DD` string (empty when absent)."""
		if not value:
			return ""
		text = str(value).strip()
		try:
			return datetime.fromisoformat(text).date().isoformat()
		except ValueError:
			# not a datetime: assume it is already a date (or a dateless prefix we can slice)
			return text[:10]

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

		try:
			created = response.json().get("created")
		except ValueError as exc:
			raise PaperlessControllerException(f"Paperless API returned invalid JSON for {doc_url}.") from exc
		return self._date_only(created or "")
