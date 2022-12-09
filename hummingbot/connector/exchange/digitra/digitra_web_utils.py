import time
from ssl import SSLContext
from typing import Callable, Iterable, Optional, Union

import aiohttp
from aiohttp import BasicAuth, Fingerprint as Fingerprint, hdrs
from aiohttp.typedefs import LooseHeaders, StrOrURL

import hummingbot.connector.exchange.digitra.digitra_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.connections_factory import ConnectionsFactory
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    subdomain = CONSTANTS.endpoint_subdomain(path_url)
    return CONSTANTS.REST_URL[domain].format(subdomain) + CONSTANTS.PUBLIC_API_VERSION + path_url


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    subdomain = CONSTANTS.endpoint_subdomain(path_url)
    return CONSTANTS.REST_URL[domain].format(subdomain) + CONSTANTS.PRIVATE_API_VERSION + path_url


class DigitraWsClientSession(aiohttp.ClientSession):

    def ws_connect(
            self,
            url: StrOrURL,
            *,
            method: str = hdrs.METH_GET,
            protocols: Iterable[str] = (),
            timeout: float = 10.0,
            receive_timeout: Optional[float] = None,
            autoclose: bool = True,
            autoping: bool = True,
            heartbeat: Optional[float] = None,
            auth: Optional[BasicAuth] = None,
            origin: Optional[str] = None,
            headers: Optional[LooseHeaders] = None,
            proxy: Optional[StrOrURL] = None,
            proxy_auth: Optional[BasicAuth] = None,
            ssl: Union[SSLContext, bool, None, Fingerprint] = None,
            verify_ssl: Optional[bool] = None,
            fingerprint: Optional[bytes] = None,
            ssl_context: Optional[SSLContext] = None,
            proxy_headers: Optional[LooseHeaders] = None,
            compress: int = 0,
            max_msg_size: int = 4 * 1024 * 1024,
    ):
        """
        Purely to override aiohttp ws_connect call to ensure 'autoping' is set to True since hummingbot hardcodes it as False
        """
        return super() \
            .ws_connect(url,
                        # Stupid hard fix
                        autoping=True,
                        # just re-pass remaining params
                        method=method, protocols=protocols, timeout=timeout, receive_timeout=receive_timeout,
                        autoclose=autoclose, heartbeat=heartbeat, auth=auth, origin=origin, headers=headers,
                        proxy=proxy, proxy_auth=proxy_auth, ssl=ssl, verify_ssl=verify_ssl, fingerprint=fingerprint,
                        ssl_context=ssl_context, proxy_headers=proxy_headers, compress=compress,
                        max_msg_size=max_msg_size)


class DigitraConnectionsFactory(ConnectionsFactory):
    """
    Extends ConnectionsFactory only to return custom aiohttp.ClientSession which ensures autoping
    """

    async def _get_shared_client(self) -> aiohttp.ClientSession:
        self._shared_client = self._shared_client or DigitraWsClientSession()

        return self._shared_client


def build_api_factory(
        throttler: Optional[AsyncThrottler] = None,
        time_synchronizer: Optional[TimeSynchronizer] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
        time_provider: Optional[Callable] = None,
        auth: Optional[AuthBase] = None, ) -> WebAssistantsFactory:
    # time_synchronizer = time_synchronizer or TimeSynchronizer()
    # time_provider = time_provider or (lambda: get_current_server_time(
    #     throttler=throttler,
    #     domain=domain,
    # ))
    throttler = throttler or create_throttler()
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[
            # TimeSynchronizerRESTPreProcessor(synchronizer=time_synchronizer, time_provider=time_provider),
        ])
    api_factory._connections_factory = DigitraConnectionsFactory()
    return api_factory


def build_api_factory_without_time_synchronizer_pre_processor(throttler: AsyncThrottler) -> WebAssistantsFactory:
    api_factory = WebAssistantsFactory(throttler=throttler)
    return api_factory


def create_throttler() -> AsyncThrottler:
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(
        throttler: Optional[AsyncThrottler] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
) -> float:
    # throttler = throttler or create_throttler()
    # api_factory = build_api_factory_without_time_synchronizer_pre_processor(throttler=throttler)

    return time.perf_counter()
