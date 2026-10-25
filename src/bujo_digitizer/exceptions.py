class PaperlessControllerException(Exception):
	"""Raised when the Paperless API cannot be reached or rejects a request."""


class ObsidianControllerException(Exception):
	"""Raised when an Obsidian note update fails (missing note/section, invalid date, IO error)."""
