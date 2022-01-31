from decimal import Decimal
from pydantic import BaseModel, validator


TWO_PLACES = Decimal(10) ** -2


class AmountPrecision(BaseModel):
    gross: Decimal
    net: Decimal

    def __getitem__(self, name):
        return getattr(self, name)


class Amount(AmountPrecision):
    @validator('gross', 'net')
    def _round_amount(cls, value: Decimal):
        return value.quantize(TWO_PLACES)
