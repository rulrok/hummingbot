from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

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

AUTH_URL = {
    "digitra_testnet": "https://digitra-stg-hb.auth.us-east-1.amazoncognito.com/oauth2/token"
}

PUBLIC_API_VERSION = "v1"
PRIVATE_API_VERSION = "v1"

# Public endpoints
API_HEALTH_CHECK_PATH = "/health-check"
API_ALL_MARKETS_PATH = "/markets"
API_MARKET_PATH = "/markets/{market_symbol}"

# Private endpoints
API_BALANCES_PATH = "/balances"
API_ORDERS_PATH = "/orders"
API_ORDER_PATH = "/orders/{order_id}"

ENDPOINT_SUBDOM_MAP = {
    # Trade
    API_HEALTH_CHECK_PATH: REST_SUBDOM_TRADE,
    API_MARKET_PATH: REST_SUBDOM_TRADE,
    API_ALL_MARKETS_PATH: REST_SUBDOM_TRADE,
    API_ORDERS_PATH: REST_SUBDOM_TRADE,

    # Balance
    API_BALANCES_PATH: REST_SUBDOM_BALANCE
}

WS_PING_INTERVAL = 10

DIFF_EVENT_TYPE = "diffDepth"
TRADE_EVENT_TYPE = "trade"
SNAPSHOT_EVENT_TYPE = "depth"

ORDER_STATE_MAPPING = {
    "SUBMITTING": OrderState.PENDING_CREATE,
    "OPEN": OrderState.OPEN,
    "PENDING_CANCELING": OrderState.PENDING_CANCEL,
    "CANCELED": OrderState.CANCELED,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "FILLED": OrderState.FILLED,
    # TODO Revise two states below
    "PENDING_BALANCE": OrderState.PENDING_APPROVAL,
    "CANCELED_PENDING_BALANCE": OrderState.FAILED
}


def endpoint_subdomain(path: str) -> str or None:
    for k, v in ENDPOINT_SUBDOM_MAP.items():
        if str(path).__contains__(k):
            return v

    raise Exception("Missing endpoint subdomain mapping")


# Rate limit portion

RATE_SHARED_LIMITER = "AllHTTP"
RATE_SEND_ORDER = API_ORDERS_PATH
RATE_CANCEL_ORDER = "DEL " + API_ORDERS_PATH.format(order_id="*")
MAX_REQUESTS = 750

MINUTE = 60

RATE_LIMITS = [
    # REST API Pool
    RateLimit(limit_id=RATE_SHARED_LIMITER, limit=MAX_REQUESTS, time_interval=MINUTE),

    # REST Endpoints
    RateLimit(limit_id=API_HEALTH_CHECK_PATH, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(RATE_SHARED_LIMITER)]),

    RateLimit(limit_id=API_ALL_MARKETS_PATH, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(RATE_SHARED_LIMITER)]),

    RateLimit(limit_id=API_BALANCES_PATH, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(RATE_SHARED_LIMITER)]),

    RateLimit(limit_id=RATE_CANCEL_ORDER, limit=15, time_interval=1,
              linked_limits=[LinkedLimitWeightPair(RATE_SHARED_LIMITER)]),

    RateLimit(limit_id=RATE_SEND_ORDER, limit=15, time_interval=1,
              linked_limits=[LinkedLimitWeightPair(RATE_SHARED_LIMITER)]),
]
