import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from dateutil import parser

import hummingbot.connector.exchange.digitra.digitra_constants as CONSTANTS
from hummingbot.connector.exchange.digitra import digitra_web_utils as web_utils
from hummingbot.connector.exchange.digitra.digitra_order_book import DigitraOrderBook
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant

if TYPE_CHECKING:
    from hummingbot.connector.exchange.digitra.digitra_exchange import DigitraExchange


class DigitraAPIOrderBookDataSource(OrderBookTrackerDataSource):
    _trading_pair_symbol_map: Dict[str, Mapping[str, str]] = {}
    _mapping_initialization_lock = asyncio.Lock()

    def __init__(self,
                 trading_pairs: List[str],
                 connector: 'DigitraExchange',
                 api_factory: Optional[WebAssistantsFactory] = None,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 throttler: Optional[AsyncThrottler] = None,
                 time_synchronizer: Optional[TimeSynchronizer] = None):
        super().__init__(trading_pairs)
        self._connector = connector
        self._domain = domain
        self._time_synchronizer = time_synchronizer
        self._throttler = throttler
        self._api_factory = api_factory or web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
        )

    async def get_last_traded_prices(self,
                                     trading_pairs: List[str],
                                     domain: Optional[str] = None) -> Dict[str, float]:
        rest_assistant = await self._api_factory.get_rest_assistant()

        prices_response = await rest_assistant.execute_request(
            url=web_utils.public_rest_url(CONSTANTS.API_ALL_MARKETS_PATH, self._domain),
            method=RESTMethod.GET,
            params={
                "expand": "PRICES"
            },
            throttler_limit_id=CONSTANTS.HTTP_ENDPOINTS_LIMIT_ID
        )

        trading_pairs_prices = [(p.get('id'), p.get('prices')["price"]) for p in prices_response['result'] if
                                p.get("id") in trading_pairs]

        return dict(trading_pairs_prices)

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        market_trading_pair = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        rest_assistant = await self._api_factory.get_rest_assistant()
        snapshot_response = await rest_assistant.execute_request(
            url=web_utils.public_rest_url(CONSTANTS.API_MARKET_PATH.format(market_symbol=market_trading_pair), self._domain),
            method=RESTMethod.GET,
            params={
                "expand": "ORDER_BOOK"
            },
            throttler_limit_id=CONSTANTS.HTTP_ENDPOINTS_LIMIT_ID
        )

        snapshot_data: Dict[str, Any] = snapshot_response["result"]
        snapshot_timestamp: float = self._time()

        return DigitraOrderBook.snapshot_message_from_exchange_rest(
            snapshot_data, snapshot_timestamp,
            metadata={"update_id": snapshot_timestamp}
        )

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        # trade_data: Dict[str, Any] = raw_message["data"]
        # trade_timestamp: int = int(parser.isoparse(trade_data["time"]).timestamp())
        # trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(symbol=trade_data["market"])

        # message_content = {
        #     "trading_pair": trading_pair,
        #     # TODO
        #     # "trade_type": (float(TradeType.SELL.value)
        #     #                if trade_data["side"] == "sell"
        #     #                else float(TradeType.BUY.value)),
        #     "trade_id": trade_timestamp,
        #     "update_id": trade_timestamp,
        #     "price": trade_data["last"],
        #     # "amount": trade_data["x"], TODO
        # }
        # trade_message: Optional[OrderBookMessage] = OrderBookMessage(
        #     message_type=OrderBookMessageType.TRADE,
        #     content=message_content,
        #     timestamp=trade_timestamp)
        #
        # message_queue.put_nowait(trade_message)

        pass

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        pass

    async def _parse_order_book_snapshot_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        snapshot_data: Dict[str, Any] = {}
        snapshot_timestamp: float = parser.isoparse(raw_message.get("data")["time"]).timestamp()

        ob = DigitraOrderBook.snapshot_message_from_exchange_rest(
            snapshot_data, snapshot_timestamp,
            metadata={
                "id": raw_message.get("market"),
                "order_book": {
                    "bids": [{"price": bid[0], "size": bid[1]} for bid in raw_message["data"]["bids"]],
                    "asks": [{"price": ask[0], "size": ask[1]} for ask in raw_message["data"]["asks"]],
                },
                "update_id": snapshot_timestamp
            }
        )

        message_queue.put_nowait(ob)

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        channel = event_message.get("channel")
        t = event_message.get("type")

        if t == "subscribed":
            self.logger().info(event_message)
            return "subscribed"

        if t == "pong":
            self.logger().debug(event_message)
            return "pong"

        if t == "update":
            if channel == "ticker":
                return "ticker"
            if channel == "orderbook":
                return self._snapshot_messages_queue_key  # Digitra sends the whole book on each update as of today

        return "unknown"

    async def _process_message_for_unknown_channel(self,
                                                   event_message: Dict[str, Any],
                                                   websocket_assistant: WSAssistant):
        if "pong" == event_message["type"]:
            self.logger().info("OB pong received")
            return

        pass

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribes to the trade events and diff orders events through the provided websocket connection.
        :param ws: the websocket assistant used to connect to the exchange
        """
        try:
            for trading_pair in self._trading_pairs:
                symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

                # ticker_payload = {
                #     "op": "subscribe",
                #     "channel": "ticker",
                #     "market": symbol,
                # }
                # subscribe_ticker_request: WSJSONRequest = WSJSONRequest(payload=ticker_payload)
                # await ws.send(subscribe_ticker_request)

                depth_payload = {
                    "op": "subscribe",
                    "channel": "orderbook",
                    "market": symbol,
                }
                subscribe_orderbook_request: WSJSONRequest = WSJSONRequest(payload=depth_payload)

                await ws.send(subscribe_orderbook_request)

                self.logger().info(f"Subscribed to public order book and trade channels of {trading_pair}...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred subscribing to order book trading and delta streams...",
                exc_info=True
            )
            raise

    async def _connected_websocket_assistant(self) -> WSAssistant:
        websocket_assistant: WSAssistant = await self._api_factory.get_ws_assistant()
        await websocket_assistant.connect(
            ws_url=CONSTANTS.WSS_URL[self._domain],
            ping_timeout=500
        )

        await self.__ping_loop(websocket_assistant)

        return websocket_assistant

    async def __ping_loop(self, websocket_assistant):
        await self.__send_ping(websocket_assistant)
        await asyncio.sleep(CONSTANTS.WS_PING_INTERVAL)

        asyncio.ensure_future(self.__ping_loop(websocket_assistant))

    async def __send_ping(self, websocket_assistant):
        payload = {"op": "ping"}
        ping_request = WSJSONRequest(payload=payload)
        await websocket_assistant.send(request=ping_request)
        self.logger().info('OB ping sent')
