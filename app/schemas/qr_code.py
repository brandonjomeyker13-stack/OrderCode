# app/schemas/qr_code.py
from pydantic import BaseModel, ConfigDict

from app.schemas.common import TimestampSchema


class QRCodeOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    activo: bool