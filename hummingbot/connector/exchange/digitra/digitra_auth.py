import time
from typing import Optional

import aiohttp
import jwt

from hummingbot.connector.exchange.digitra import digitra_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class DigitraAuth(AuthBase):

    def __init__(self,
                 jwt: str,
                 time_provider: TimeSynchronizer,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 refresh_token: Optional[str] = None,
                 api_key: Optional[str] = None,
                 secret_key: Optional[str] = None
                 ):
        self._domain = domain
        self._refresh_token = refresh_token
        self._jwt = jwt
        self.api_key = api_key
        self.secret_key = secret_key
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        auth_headers = await self.__generate_auth_headers()

        headers = {
            "Accept": "application/json"
        }
        if request.headers is not None:
            headers.update(request.headers)

        headers.update(auth_headers)
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        token = await self.get_jwt()
        request.payload = {
            "op": "login",
            "key": token
        }
        return request

    async def get_jwt(self) -> str:
        await self.__ensure_jwt()
        return self._jwt

    async def __ensure_jwt(self):
        unvalidated = jwt.decode(self._jwt, verify=False)
        if unvalidated["exp"] - time.time() > 0:
            pass

        if self._refresh_token is None:
            raise Exception("JWT is expired and no refresh_token has been provided")
        # NOTE: The token doesn't follow an expected format, but we could potentially verify it
        # else:
        #     try:
        #         jwt.decode(self._refresh_token, verify=False)
        #     except jwt.DecodeError:
        #         raise Exception("Invalid refresh token")

        url = CONSTANTS.AUTH_URL[self._domain]
        data = aiohttp.FormData()
        data.add_field("grant_type", "refresh_token")
        data.add_field("client_id", unvalidated["client_id"])
        data.add_field("refresh_token", self._refresh_token)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                tokens = await response.json()
                self._jwt = tokens["access_token"]

    async def __generate_auth_headers(self):
        """
        Adds Authorization header with jwt token to request
        """
        token = await self.get_jwt()
        headers = {
            "Authorization": "Bearer " + token
        }
        return headers
