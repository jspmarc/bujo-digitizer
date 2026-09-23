import logging

from bujo_digitizer.config import get_settings

_configured = False


def get_logger(name: str | None = None) -> logging.Logger:
	global _configured
	if not _configured:
		_setup()
		_configured = True

	settings = get_settings()
	if name is None:
		return logging.getLogger(settings.app_name)
	return logging.getLogger(name)


def _setup() -> None:
	settings = get_settings()
	level = getattr(logging, settings.log_level.upper(), logging.INFO)

	handler = logging.StreamHandler()
	handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

	app_logger = logging.getLogger(settings.app_name)
	app_logger.setLevel(level)
	app_logger.addHandler(handler)
