import logging
from importlib import resources

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bujo_digitizer.router import router

logging.basicConfig(level=logging.DEBUG)

app = FastAPI(title="Bujo Digitizer", version="0.1.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=resources.files("bujo_digitizer").joinpath("static")), name="static")


def main() -> None:
	import uvicorn

	uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
	main()
