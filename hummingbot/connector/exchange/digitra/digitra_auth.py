from typing import Any, Dict, Optional

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class DigitraAuth(AuthBase):

    def __init__(self, jwt: str, api_key: Optional[str], secret_key: Optional[str], time_provider: TimeSynchronizer):
        self.jwt = jwt
        self.api_key = api_key
        self.secret_key = secret_key
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        digitra_auth_headers = self.__generate_auth_headers(params=request.params)
        headers = {}
        if request.headers is not None:
            headers.update(request.headers)
        headers.update(digitra_auth_headers)
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        request.payload = {
            "op": "login",
            "key": self.jwt
        }
        return request  # pass-through

    def __generate_auth_headers(self, params: Optional[Dict[str, Any]]):
        """
        Adds Authorization header with jwt token to request
        """
        request_params = params or {}
        request_params["Authorization"] = "Bearer: " + self.jwt
        return request_params
