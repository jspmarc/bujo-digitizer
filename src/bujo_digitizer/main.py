import asyncio
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bujo_digitizer.config import get_settings
from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, PaperlessController
from bujo_digitizer.router import Router
from bujo_digitizer.worker import DigitizeWorker


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
	app.include_router(routes.router)
	app.mount("/static", StaticFiles(directory=resources.files("bujo_digitizer").joinpath("static")), name="static")
	return app


app = create_app()


def main() -> None:
	import uvicorn

	uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
	main()
