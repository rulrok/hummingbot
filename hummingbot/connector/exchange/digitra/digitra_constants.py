from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

DEFAULT_DOMAIN = "digitra"

REST_SUBDOM_TRADE = "trade"
REST_SUBDOM_BALANCE = "balance"

REST_URL = {
    "digitra": "https://{0}.api.digitra.com/",
    "digitra_testnet": "https://{0}.stg-hb.cloud.digitra.com/",
}

WSS_URL = {
    "digitra_testnet": "wss://taxi-driver-websocket.dev.cloud.atris.com.br/v1/ws"
}

PUBLIC_API_VERSION = "v1"
PRIVATE_API_VERSION = "v1"

# Public endpoints
HEALTH_CHECK_URL = "/health-check"
API_ALL_MARKETS = "/markets"
API_MARKET = "/markets/{market_symbol}"

# Private endpoints
API_BALANCES = "/balances"

ENDPOINT_SUBDOM_MAP = {
    # Trade
    HEALTH_CHECK_URL: REST_SUBDOM_TRADE,
    API_MARKET: REST_SUBDOM_TRADE,
    API_ALL_MARKETS: REST_SUBDOM_TRADE,

    # Balance
    API_BALANCES: REST_SUBDOM_BALANCE
}

WS_HEARTBEAT_TIME_INTERVAL = 30

DIFF_EVENT_TYPE = "diffDepth"
TRADE_EVENT_TYPE = "trade"
SNAPSHOT_EVENT_TYPE = "depth"


def endpoint_subdomain(path: str) -> str or None:
    for k, v in ENDPOINT_SUBDOM_MAP.items():
        if str(path).__contains__(k):
            return v

    return None

    # Rate limit portion


HTTP_ENDPOINTS_LIMIT_ID = "AllHTTP"
MAX_REQUESTS = 1500

MINUTE = 60

RATE_LIMITS = [
    # REST API Pool
    RateLimit(limit_id=HTTP_ENDPOINTS_LIMIT_ID, limit=MAX_REQUESTS, time_interval=MINUTE),

    # REST Endpoints
    RateLimit(limit_id=HEALTH_CHECK_URL, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(HTTP_ENDPOINTS_LIMIT_ID)]),

    RateLimit(limit_id=API_ALL_MARKETS, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(HTTP_ENDPOINTS_LIMIT_ID)]),

    RateLimit(limit_id=API_BALANCES, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(HTTP_ENDPOINTS_LIMIT_ID)])
]
