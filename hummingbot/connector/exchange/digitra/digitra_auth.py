from typing import Optional

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class DigitraAuth(AuthBase):

    def __init__(self, jwt: str, time_provider: TimeSynchronizer, api_key: Optional[str] = None,
                 secret_key: Optional[str] = None):
        self.jwt = jwt
        self.api_key = api_key
        self.secret_key = secret_key
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        auth_headers = self.__generate_auth_headers()

        headers = {
            "Accept": "application/json"
        }
        if request.headers is not None:
            headers.update(request.headers)

        headers.update(auth_headers)
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        request.payload = {
            "op": "login",
            "key": self.jwt
        }
        return request

    def __generate_auth_headers(self):
        """
        Adds Authorization header with jwt token to request
        """
        headers = {
            "Authorization": "Bearer " + self.jwt
        }
        return headers
