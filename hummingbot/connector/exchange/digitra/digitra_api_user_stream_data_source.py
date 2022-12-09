import asyncio
from typing import Any, Dict, Optional

import hummingbot.connector.exchange.digitra.digitra_constants as CONSTANTS
import hummingbot.connector.exchange.digitra.digitra_web_utils as web_utils
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant


class DigitraAPIUserStreamDataSource(UserStreamTrackerDataSource):
    def __init__(self,
                 auth: AuthBase,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 api_factory: Optional[WebAssistantsFactory] = None,
                 throttler: Optional[AsyncThrottler] = None,
                 time_synchronizer: Optional[TimeSynchronizer] = None):
        super().__init__()
        self._auth = auth
        self._time_synchronizer = time_synchronizer
        self._domain = domain
        self._throttler = throttler
        self._api_factory = api_factory or web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth)
        self._ws_assistant: Optional[WSAssistant] = None
        self._last_ws_message_sent_timestamp = 0

    async def _connected_websocket_assistant(self) -> WSAssistant:
        websocket_assistant: WSAssistant = await self._api_factory.get_ws_assistant()
        await websocket_assistant.connect(
            ws_url=CONSTANTS.WSS_URL[self._domain],
        )

        self.logger().info("Initialized")

        # Force sending any message which will be overriden with auth payload by auth module
        await websocket_assistant.send(WSJSONRequest(is_auth_required=True, payload={}))
        self.logger().info("Authenticated")

        await self.__ping_loop(websocket_assistant)

        return websocket_assistant

    async def _subscribe_channels(self, websocket_assistant: WSAssistant):
        payload = {
            "op": "subscribe",
            "channel": "orders"
        }
        user_orders_request = WSJSONRequest(payload=payload)
        await websocket_assistant.subscribe(request=user_orders_request)

    async def __ping_loop(self, websocket_assistant: WSAssistant):
        await self._send_ping(websocket_assistant)
        await self._sleep(CONSTANTS.WS_PING_INTERVAL)

        asyncio.ensure_future(self.__ping_loop(websocket_assistant))

    async def _send_ping(self, websocket_assistant: WSAssistant):
        payload = {"op": "ping"}
        ping_request = WSJSONRequest(payload=payload)
        await websocket_assistant.send(request=ping_request)

    async def _process_event_message(self, event_message: Dict[str, Any], queue: asyncio.Queue):
        if len(event_message) > 0:
            t = event_message.get("type")
            if t == "error":
                code = event_message.get("code")
                msg = event_message.get("msg")

                raise Exception(f'[{code}] {msg}')
            elif t == "success":
                msg = event_message.get("msg")
                self.logger().info(msg)
            elif t == "pong":
                pass

            queue.put_nowait(event_message)

    async def _on_user_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
        await super()._on_user_stream_interruption(websocket_assistant)

        await self._sleep(5)
