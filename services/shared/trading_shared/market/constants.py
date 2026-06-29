"""Angel One SmartAPI WebSocket exchange type codes."""

NSE_CM = 1
NSE_FO = 2
BSE_CM = 3
BSE_FO = 4
MCX_FO = 5
NCX_FO = 7
CDE_FO = 13

LTP_MODE = 1
QUOTE_MODE = 2
SNAP_QUOTE_MODE = 3
DEPTH_MODE = 4

EXCHANGE_TYPE_MAP = {
    NSE_CM: "NSE_CM",
    NSE_FO: "NSE_FO",
    BSE_CM: "BSE_CM",
    BSE_FO: "BSE_FO",
}

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Angel One index tokens (NSE CM)
NIFTY_INDEX_TOKEN = "99926000"
BANKNIFTY_INDEX_TOKEN = "99926009"
NIFTY_FUT_TOKEN = "26000"  # resolved dynamically from scrip master when available

CANDLE_INTERVALS = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY",
}

REDIS_TICK_PREFIX = "market:tick"
REDIS_CANDLE_PREFIX = "market:candle"
REDIS_SCAN_KEY = "market:scan:latest"
REDIS_STREAM_STATUS_KEY = "market:stream:status"
REDIS_OPTION_CHAIN_PREFIX = "market:option_chain"
REDIS_SECTOR_STRENGTH_KEY = "market:sector:strength"

PUBSUB_TICKS = "market:ticks"
PUBSUB_SCAN = "market:scan"
PUBSUB_OPTION_CHAIN = "market:option_chain"

PRICE_DIVISOR = 100.0
