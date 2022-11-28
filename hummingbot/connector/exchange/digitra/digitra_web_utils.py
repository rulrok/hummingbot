import hummingbot.connector.exchange.digitra.digitra_constants as CONSTANTS


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    return CONSTANTS.REST_URL.format(domain) + CONSTANTS.PUBLIC_API_VERSION + path_url


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    return CONSTANTS.REST_URL.format(domain) + CONSTANTS.PRIVATE_API_VERSION + path_url
