from pydantic import BaseModel


class DigitizeRequest(BaseModel):
    image_url: str
    format: str = "markdown"


class DigitizeResponse(BaseModel):
    id: str
    content: str
    format: str


class HealthResponse(BaseModel):
    status: str
