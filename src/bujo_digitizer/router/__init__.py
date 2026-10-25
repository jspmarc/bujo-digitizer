from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from bujo_digitizer.config import Settings
from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore
from bujo_digitizer.controllers import DigitizeController, ObsidianController, PaperlessController
from bujo_digitizer.router.digitize import DigitizeRouter
from bujo_digitizer.router.reviews import ReviewsRouter


class Router:
	"""HTTP routes for the digitizer. Dependencies are injected from main.py."""

	def __init__(
		self,
		*,
		settings: Settings,
		controller: DigitizeController,
		paperless_controller: PaperlessController,
		obsidian_controller: ObsidianController,
		store: DigitizeResultStore,
		jobs: DigitizeJobStore,
		templates: Jinja2Templates,
	) -> None:
		self._templates: Jinja2Templates = templates
		self._router: APIRouter = APIRouter()
		self._register_routes(
			settings=settings,
			controller=controller,
			paperless_controller=paperless_controller,
			obsidian_controller=obsidian_controller,
			store=store,
			jobs=jobs,
		)

	@property
	def router(self) -> APIRouter:
		return self._router

	def _register_routes(
		self,
		*,
		settings: Settings,
		controller: DigitizeController,
		paperless_controller: PaperlessController,
		obsidian_controller: ObsidianController,
		store: DigitizeResultStore,
		jobs: DigitizeJobStore,
	) -> None:
		self._router.add_api_route("/", self.index, methods=["GET"], include_in_schema=False)
		self._router.include_router(
			DigitizeRouter(
				settings=settings,
				controller=controller,
				store=store,
				jobs=jobs,
				templates=self._templates,
			).router
		)
		self._router.include_router(
			ReviewsRouter(
				settings=settings,
				paperless_controller=paperless_controller,
				obsidian_controller=obsidian_controller,
				store=store,
				templates=self._templates,
				jobs=jobs,
			).router
		)

	async def index(self, request: Request):
		return self._templates.TemplateResponse(request, "index.html")
