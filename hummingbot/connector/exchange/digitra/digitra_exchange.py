from typing import TYPE_CHECKING, List, Optional

from hummingbot.connector.exchange.digitra import digitra_constants as CONSTANTS, digitra_web_utils as web_utils
from hummingbot.connector.exchange_py_base import ExchangePyBase

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter

s_logger = None


class DigitraExchange(ExchangePyBase):
    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 digitra_api_key: str,
                 digitra_api_secret: str,
                 digitra_jwt: str,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.api_key = digitra_api_key
        self.secret_key = digitra_api_secret
        self.api_jwt = digitra_jwt
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._last_trades_poll_digitra_timestamp = 1.0
        super().__init__(client_config_map)
