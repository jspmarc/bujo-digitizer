import logging

from fastapi import FastAPI

from bujo_digitizer.router import router

logging.basicConfig(level=logging.DEBUG)

app = FastAPI(title="Bujo Digitizer", version="0.1.0")
app.include_router(router)


def main() -> None:
	import uvicorn

	uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
	main()
