from bujo_digitizer.models import DigitizeRequest, DigitizeResponse, HealthResponse


class DigitizeController:
    @staticmethod
    async def digitize(request: DigitizeRequest) -> DigitizeResponse:
        return DigitizeResponse(
            id="1",
            content=f"Digitized content from {request.image_url}",
            format=request.format,
        )

    @staticmethod
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")
