from pydantic import BaseModel, Field


class AngelLoginRequest(BaseModel):
    client_code: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1)
    totp: str = Field(..., min_length=6, max_length=6)


class AngelLoginResponse(BaseModel):
    jwt_token: str
    refresh_token: str
    feed_token: str | None = None
    client_code: str


class PlaceOrderRequest(BaseModel):
    variety: str = "NORMAL"
    tradingsymbol: str
    symboltoken: str
    transactiontype: str
    exchange: str
    ordertype: str
    producttype: str
    duration: str = "DAY"
    price: str = "0"
    triggerprice: str = "0"
    squareoff: str = "0"
    stoploss: str = "0"
    quantity: str
    ordertag: str | None = None


class ModifyOrderRequest(BaseModel):
    variety: str
    orderid: str
    ordertype: str | None = None
    producttype: str | None = None
    duration: str | None = None
    price: str | None = None
    quantity: str | None = None
    triggerprice: str | None = None


class CancelOrderRequest(BaseModel):
    variety: str
    orderid: str


class LTPRequest(BaseModel):
    exchange: str
    tradingsymbol: str
    symboltoken: str


class CandleRequest(BaseModel):
    exchange: str
    symboltoken: str
    interval: str
    fromdate: str
    todate: str


class SearchScripRequest(BaseModel):
    exchange: str
    searchscrip: str
