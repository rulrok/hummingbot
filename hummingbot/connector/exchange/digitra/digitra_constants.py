from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

DEFAULT_DOMAIN = "api"

REST_SUBDOM_TRADE = "trade"
REST_SUBDOM_BALANCE = "balance"

REST_URL = "https://{0}.{1}.digitra.com/"

PUBLIC_API_VERSION = "v1"
PRIVATE_API_VERSION = "v1"

# Public endpoints
HEALTH_CHECK_URL = "/health-check"
API_MARKETS = "/markets/{}"

# Private endpoints
API_BALANCES = "/balances"

ENDPOINT_SUBDOM_MAP = {
    # Trade
    HEALTH_CHECK_URL: REST_SUBDOM_TRADE,
    API_MARKETS: REST_SUBDOM_TRADE,

    # Balance
    API_BALANCES: REST_SUBDOM_BALANCE
}


def endpoint_subdomain(path: str) -> str or None:
    for k, v in ENDPOINT_SUBDOM_MAP.items():
        if str(k).__contains__(path):
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

    RateLimit(limit_id=API_MARKETS.format("")[:-1], limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(HTTP_ENDPOINTS_LIMIT_ID)]),

    RateLimit(limit_id=API_BALANCES, limit=MAX_REQUESTS, time_interval=MINUTE,
              linked_limits=[LinkedLimitWeightPair(HTTP_ENDPOINTS_LIMIT_ID)])
]
