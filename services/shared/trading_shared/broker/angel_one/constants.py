"""Angel One SmartAPI constants for NSE/BSE trading."""

ROOT_URL = "https://apiconnect.angelone.in"

EXCHANGE_NSE = "NSE"
EXCHANGE_BSE = "BSE"
EXCHANGE_NFO = "NFO"
EXCHANGE_BFO = "BFO"

PRODUCT_INTRADAY = "INTRADAY"
PRODUCT_DELIVERY = "DELIVERY"
PRODUCT_CARRYFORWARD = "CARRYFORWARD"
PRODUCT_MARGIN = "MARGIN"

ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_STOPLOSS_LIMIT = "STOPLOSS_LIMIT"
ORDER_TYPE_STOPLOSS_MARKET = "STOPLOSS_MARKET"

TRANSACTION_BUY = "BUY"
TRANSACTION_SELL = "SELL"

VARIETY_NORMAL = "NORMAL"
VARIETY_STOPLOSS = "STOPLOSS"
VARIETY_AMO = "AMO"

DURATION_DAY = "DAY"
DURATION_IOC = "IOC"

ROUTES = {
    "login": "/rest/auth/angelbroking/user/v1/loginByPassword",
    "logout": "/rest/secure/angelbroking/user/v1/logout",
    "refresh_token": "/rest/auth/angelbroking/jwt/v1/generateTokens",
    "profile": "/rest/secure/angelbroking/user/v1/getProfile",
    "rms": "/rest/secure/angelbroking/user/v1/getRMS",
    "place_order": "/rest/secure/angelbroking/order/v1/placeOrder",
    "modify_order": "/rest/secure/angelbroking/order/v1/modifyOrder",
    "cancel_order": "/rest/secure/angelbroking/order/v1/cancelOrder",
    "order_book": "/rest/secure/angelbroking/order/v1/getOrderBook",
    "trade_book": "/rest/secure/angelbroking/order/v1/getTradeBook",
    "position": "/rest/secure/angelbroking/order/v1/getPosition",
    "holding": "/rest/secure/angelbroking/portfolio/v1/getHolding",
    "ltp": "/rest/secure/angelbroking/order/v1/getLtpData",
    "candles": "/rest/secure/angelbroking/historical/v1/getCandleData",
    "search_scrip": "/rest/secure/angelbroking/order/v1/searchScrip",
    "convert_position": "/rest/secure/angelbroking/order/v1/convertPosition",
}

INDEX_TOKENS = {
    "NIFTY": {"exchange": EXCHANGE_NSE, "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "BANKNIFTY": {"exchange": EXCHANGE_NSE, "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
}
