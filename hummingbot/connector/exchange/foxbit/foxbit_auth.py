import hashlib
import hmac
from datetime import datetime, timezone

from hummingbot.connector.exchange.foxbit import foxbit_web_utils as web_utils
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class FoxbitAuth(AuthBase):

    def __init__(self, api_key: str, secret_key: str, user_id: str, time_provider: TimeSynchronizer):
        self.api_key = api_key
        self.secret_key = secret_key
        self.user_id = user_id
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Signs the request using HMAC and adds it along with the necessary HTTP headers.
        Each request is individually signed off.
        """

        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1e3))

        method = str(request.method).upper()
        path = web_utils.rest_endpoint_url(request.url)

        query = ""
        if request.params is not None:
            query = ''
            i = 0
            for p in request.params:
                k = p
                v = request.params[p]
                if i == 0:
                    query = query + f"{k}={v}"
                else:
                    query = query + f"&{k}={v}"
                i += 1

        body = request.data if request.data is not None else ""

        payload = '{}{}{}{}{}'.format(timestamp, method, path, query, body)

        signature = hmac.new(self.secret_key.encode("utf8"),
                             payload.encode("utf8"),
                             hashlib.sha256).digest().hex()

        foxbit_header = {
            "X-FB-ACCESS-KEY": self.api_key,
            "X-FB-ACCESS-SIGNATURE": signature,
            "X-FB-ACCESS-TIMESTAMP": timestamp,
        }

        headers = {}
        if request.headers is not None:
            headers.update(request.headers)
        headers.update(foxbit_header)
        request.headers = headers

        return request

    async def ws_authenticate(self,
                              request: WSRequest,
                              ) -> WSRequest:
        """
        This method is intended to configure a websocket request to be authenticated.
        It should be used with empty requests to send an initial login payload.
        :param request: the request to be configured for authenticated interaction
        """
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1e3)

        msg = '{}{}{}'.format(timestamp,
                              self.user_id,
                              self.api_key)

        signature = hmac.new(self.secret_key.encode("utf8"),
                             msg.encode("utf8"),
                             hashlib.sha256).digest().hex()

        payload = {
            "APIKey": self.api_key,
            "Signature": signature,
            "UserId": self.user_id,
            "Nonce": timestamp
        }

        if hasattr(request, 'payload'):
            payload.update(request.payload)

        request.payload = payload
        return request
