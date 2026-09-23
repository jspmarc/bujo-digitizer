import asyncio
import time
from contextlib import asynccontextmanager
from importlib import resources
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bujo_digitizer.config import get_settings
from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.logger import get_logger
from bujo_digitizer.router import Router
from bujo_digitizer.worker import DigitizeWorker

logger = get_logger(__name__)


def create_app() -> FastAPI:
	settings = get_settings()

	store = DigitizeResultStore(settings.sqlite_path)
	store.initialize()
	jobs = DigitizeJobStore(settings.sqlite_path)
	jobs.initialize()

	controller = DigitizeController()
	paperless_controller = PaperlessController(settings.paperless_base_url, settings.paperless_token)
	worker = DigitizeWorker(
		jobs,
		store,
		controller,
		paperless_controller,
		poll_interval=settings.worker_poll_seconds,
		concurrency=settings.worker_concurrency,
		retry_interval=settings.worker_retry_interval_seconds,
	)
	templates = Jinja2Templates(directory=str(resources.files("bujo_digitizer").joinpath("templates")))
	routes = Router(
		settings=settings,
		controller=controller,
		paperless_controller=paperless_controller,
		store=store,
		jobs=jobs,
		templates=templates,
	)

	@asynccontextmanager
	async def lifespan(_app: FastAPI):
		await worker.start()
		try:
			yield
		finally:
			await worker.aclose()
			_ = await asyncio.gather(controller.aclose(), paperless_controller.aclose())

	app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

	@app.middleware("http")
	async def log_request(request: Request, call_next):
		request_id = str(uuid4())
		request.state.request_id = request_id
		started_at = time.perf_counter()
		try:
			response = await call_next(request)
		except Exception:
			elapsed_ms = (time.perf_counter() - started_at) * 1000
			logger.exception(
				"request_id=%s %s %s failed after %.2fms",
				request_id,
				request.method,
				request.url.path,
				elapsed_ms,
			)
			raise

		elapsed_ms = (time.perf_counter() - started_at) * 1000
		response.headers["X-Request-ID"] = request_id
		logger.info(
			"request_id=%s %s %s -> %d (%.2fms)",
			request_id,
			request.method,
			request.url.path,
			response.status_code,
			elapsed_ms,
		)
		return response

	app.include_router(routes.router)
	app.mount("/static", StaticFiles(directory=resources.files("bujo_digitizer").joinpath("static")), name="static")
	return app


app = create_app()


def main() -> None:
	import uvicorn

	uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
	main()
