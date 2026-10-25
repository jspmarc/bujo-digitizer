import asyncio

from fastapi import Request
from fastapi.templating import Jinja2Templates

from bujo_digitizer.connectors import DigitizeJobStore, DigitizeResultStore


async def render_reviews(
	request: Request,
	store: DigitizeResultStore,
	jobs: DigitizeJobStore,
	templates: Jinja2Templates,
):
	rows = await asyncio.to_thread(store.list_all)
	open_jobs = await asyncio.to_thread(jobs.list_jobs)
	return templates.TemplateResponse(request, "_review_list.html", {"rows": rows, "jobs": open_jobs})
