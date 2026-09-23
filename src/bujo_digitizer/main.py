import logging
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bujo_digitizer.router import close_resources, router, worker

logging.basicConfig(level=logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
	await worker.start()
	try:
		yield
	finally:
		await worker.aclose()
		await close_resources()


app = FastAPI(title="Bujo Digitizer", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=resources.files("bujo_digitizer").joinpath("static")), name="static")


def main() -> None:
	import uvicorn

	uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
	main()
