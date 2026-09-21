from fastapi import APIRouter

from bujo_digitizer.controllers import DigitizeController
from bujo_digitizer.models import DigitizeRequest, DigitizeResponse, HealthResponse

router = APIRouter()
controller = DigitizeController()


@router.get("/health", response_model=HealthResponse)
async def health():
    return await controller.health()


@router.post("/digitize", response_model=DigitizeResponse)
async def digitize(request: DigitizeRequest):
    return await controller.digitize(request)
