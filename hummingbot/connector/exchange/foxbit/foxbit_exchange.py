import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from bidict import bidict
from dateutil import parser

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.foxbit import (
    foxbit_constants as CONSTANTS,
    foxbit_utils,
    foxbit_web_utils as web_utils,
)
from hummingbot.connector.exchange.foxbit.foxbit_api_order_book_data_source import FoxbitAPIOrderBookDataSource
from hummingbot.connector.exchange.foxbit.foxbit_api_user_stream_data_source import FoxbitAPIUserStreamDataSource
from hummingbot.connector.exchange.foxbit.foxbit_auth import FoxbitAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import TradeFillOrderDetails, combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.event.events import MarketEvent, OrderFilledEvent
from hummingbot.core.utils.async_utils import safe_ensure_future, safe_gather
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest, WSResponse
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter

s_logger = None


class FoxbitExchange(ExchangePyBase):
    UPDATE_ORDER_STATUS_MIN_INTERVAL = 10.0

    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 foxbit_api_key: str,
                 foxbit_api_secret: str,
                 foxbit_user_id: str,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.api_key = foxbit_api_key
        self.secret_key = foxbit_api_secret
        self.user_id = foxbit_user_id
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._trading_pair_instrument_id_map: Optional[Mapping[str, str]] = None
        self._mapping_initialization_instrument_id_lock = asyncio.Lock()

        super().__init__(client_config_map)

    @property
    def authenticator(self):
        return FoxbitAuth(
            api_key=self.api_key,
            secret_key=self.secret_key,
            user_id=self.user_id,
            time_provider=self._time_synchronizer)

    @property
    def name(self) -> str:
        return "foxbit"

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        return self._domain

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.PING_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    @property
    def status_dict(self) -> Dict[str, bool]:
        return {
            "symbols_mapping_initialized": self.trading_pair_symbol_map_ready(),
            "instruments_mapping_initialized": self.trading_pair_instrument_id_map_ready(),
            "order_books_initialized": self.order_book_tracker.ready,
            "account_balance": not self.is_trading_required or len(self._account_balances) > 0,
            "trading_rule_initialized": len(self._trading_rules) > 0 if self.is_trading_required else True,
            "user_stream_initialized": self._userstream_ds.ready,
        }

    @staticmethod
    def convert_from_exchange_instrument_id(exchange_instrument_id: str) -> Optional[str]:
        return exchange_instrument_id

    @staticmethod
    def convert_to_exchange_instrument_id(hb_trading_pair: str) -> str:
        return hb_trading_pair

    @staticmethod
    def foxbit_order_type(order_type: OrderType) -> str:
        if order_type == OrderType.LIMIT or order_type == OrderType.MARKET:
            return order_type.name.upper()
        else:
            raise Exception("Order type not supported by Foxbit.")

    @staticmethod
    def to_hb_order_type(foxbit_type: str) -> OrderType:
        return OrderType[foxbit_type]

    def supported_order_types(self):
        return [OrderType.LIMIT, OrderType.MARKET]

    def trading_pair_instrument_id_map_ready(self):
        """
        Checks if the mapping from exchange symbols to client trading pairs has been initialized

        :return: True if the mapping has been initialized, False otherwise
        """
        return self._trading_pair_instrument_id_map is not None and len(self._trading_pair_instrument_id_map) > 0

    async def trading_pair_instrument_id_map(self):
        if not self.trading_pair_instrument_id_map_ready():
            async with self._mapping_initialization_instrument_id_lock:
                if not self.trading_pair_instrument_id_map_ready():
                    await self._initialize_trading_pair_instrument_id_map()
        current_map = self._trading_pair_instrument_id_map or bidict()
        return current_map

    async def exchange_instrument_id_associated_to_pair(self, trading_pair: str) -> str:
        """
        Used to translate a trading pair from the client notation to the exchange notation
        :param trading_pair: trading pair in client notation
        :return: Instrument_Id in exchange notation
        """
        symbol_map = await self.trading_pair_instrument_id_map()
        return symbol_map.inverse[trading_pair]

    async def trading_pair_associated_to_exchange_instrument_id(self, instrument_id: str,) -> str:
        """
        Used to translate a trading pair from the exchange notation to the client notation
        :param instrument_id: Instrument_Id in exchange notation
        :return: trading pair in client notation
        """
        symbol_map = await self.trading_pair_instrument_id_map()
        return symbol_map[instrument_id]

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return FoxbitAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            domain=self.domain,
            api_factory=self._web_assistants_factory)

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return FoxbitAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        """
        Calculates the estimated fee an order would pay based on the connector configuration
        :param base_currency: the order base currency
        :param quote_currency: the order quote currency
        :param order_type: the type of order (MARKET, LIMIT, LIMIT_MAKER)
        :param order_side: if the order is for buying or selling
        :param amount: the order amount
        :param price: the order price
        :return: the estimated fee for the order
        """
        return DeductedFromReturnsTradeFee(percent=self.estimate_fee_pct(False))

    def buy(self,
            trading_pair: str,
            amount: Decimal,
            order_type=OrderType.LIMIT,
            price: Decimal = s_decimal_NaN,
            **kwargs) -> str:
        """
        Creates a promise to create a buy order using the parameters

        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price

        :return: the id assigned by the connector to the order (the client id)
        """
        order_id = foxbit_utils.get_client_order_id(True)
        safe_ensure_future(self._create_order(
            trade_type=TradeType.BUY,
            order_id=order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price))
        return order_id

    def sell(self,
             trading_pair: str,
             amount: Decimal,
             order_type: OrderType = OrderType.LIMIT,
             price: Decimal = s_decimal_NaN,
             **kwargs) -> str:
        """
        Creates a promise to create a sell order using the parameters.
        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price
        :return: the id assigned by the connector to the order (the client id)
        """
        order_id = foxbit_utils.get_client_order_id(False)
        safe_ensure_future(self._create_order(
            trade_type=TradeType.SELL,
            order_id=order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price))
        return order_id

    async def _create_order(self,
                            trade_type: TradeType,
                            order_id: str,
                            trading_pair: str,
                            amount: Decimal,
                            order_type: OrderType,
                            price: Optional[Decimal] = None):
        """
        Creates a an order in the exchange using the parameters to configure it

        :param trade_type: the side of the order (BUY of SELL)
        :param order_id: the id that should be assigned to the order (the client id)
        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price
        """
        exchange_order_id = ""
        trading_rule = self._trading_rules[trading_pair]

        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER]:
            order_type = OrderType.LIMIT
            price = self.quantize_order_price(trading_pair, price)
            quantize_amount_price = Decimal("0") if price.is_nan() else price
            amount = self.quantize_order_amount(trading_pair=trading_pair, amount=amount, price=quantize_amount_price)
        else:
            amount = self.quantize_order_amount(trading_pair=trading_pair, amount=amount)

        self.start_tracking_order(
            order_id=order_id,
            exchange_order_id=None,
            trading_pair=trading_pair,
            order_type=order_type,
            trade_type=trade_type,
            price=price,
            amount=amount
        )

        if order_type not in self.supported_order_types():
            self.logger().error(f"{order_type} is not in the list of supported order types")
            self._update_order_after_failure(order_id=order_id, trading_pair=trading_pair)
            return

        if amount < trading_rule.min_order_size:
            self.logger().warning(f"{trade_type.name.title()} order amount {amount.normalize()} is lower than the minimum order"
                                  f" size {trading_rule.min_order_size}. The order will not be created.")
            self._update_order_after_failure(order_id=order_id, trading_pair=trading_pair)
            return
        if price is not None and amount * price < trading_rule.min_notional_size:
            self.logger().warning(f"{trade_type.name.title()} order notional {(amount * price).normalize()} is lower than the "
                                  f"minimum notional size {trading_rule.min_notional_size}. "
                                  "The order will not be created.")
            self._update_order_after_failure(order_id=order_id, trading_pair=trading_pair)

        try:
            exchange_order_id, update_timestamp = await self._place_order(
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                trade_type=trade_type,
                order_type=order_type,
                price=price)

            order_update: OrderUpdate = OrderUpdate(
                client_order_id=order_id,
                exchange_order_id=exchange_order_id,
                trading_pair=trading_pair,
                update_timestamp=update_timestamp,
                new_state=OrderState.OPEN,
            )
            self._order_tracker.process_order_update(order_update)

        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().network(
                f"Error submitting {trade_type.name.lower()} {order_type.name.upper()} order to {self.name_cap} for "
                f"{amount.normalize()} {trading_pair} {price.normalize()}.",
                exc_info=True,
                app_warning_msg=f"Failed to submit {trade_type.name.lower()} order to {self.name_cap}. Check API key and network connection."
            )
            self._update_order_after_failure(order_id=order_id, trading_pair=trading_pair)
        return order_id, exchange_order_id

    async def _place_order(self,
                           order_id: str,
                           trading_pair: str,
                           amount: Decimal,
                           trade_type: TradeType,
                           order_type: OrderType,
                           price: Decimal,
                           ) -> Tuple[str, float]:
        order_result = None
        amount_str = f"{amount.normalize()}"
        price_str = f"{price.normalize()}"
        type_str = FoxbitExchange.foxbit_order_type(order_type)
        side_str = CONSTANTS.SIDE_BUY if trade_type is TradeType.BUY else CONSTANTS.SIDE_SELL
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        api_params = {"market_symbol": symbol,
                      "side": side_str,
                      "quantity": amount_str,
                      "type": type_str,
                      "client_order_id": order_id,
                      }
        if order_type == OrderType.LIMIT:
            api_params["price"] = price_str

        self._logger.info(f'New order sent with these fields: {api_params}')

        order_result = await self._api_post(
            path_url=CONSTANTS.ORDER_PATH_URL,
            data=api_params,
            is_auth_required=True)
        o_id = str(order_result["id"])
        transact_time = int(datetime.now(timezone.utc).timestamp() * 1e3)
        return (o_id, transact_time)

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        params = {
            "type": "CLIENT_ORDER_ID",
            "client_order_id": order_id,
        }
        cancel_result = await self._api_put(
            path_url=CONSTANTS.CANCEL_ORDER_PATH_URL,
            data=params,
            is_auth_required=True)
        if len(cancel_result.get("data")) > 0:
            if cancel_result.get("data")[0].get('id') == int(tracked_order.exchange_order_id):
                return True
        return False

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """
        Example:
        {
            "data": [
                {
                    "symbol": "btcbrl",
                    "quantity_min": "0.00002",
                    "quantity_increment": "0.00001",
                    "price_min": "1.0",
                    "price_increment": "0.0001",
                    "base": {
                        "symbol": "btc",
                        "name": "Bitcoin",
                        "type": "CRYPTO"
                    },
                    "quote": {
                        "symbol": "btc",
                        "name": "Bitcoin",
                        "type": "CRYPTO"
                    }
                }
            ]
        }
        """
        trading_pair_rules = exchange_info_dict.get("data", [])
        retval = []
        for rule in filter(foxbit_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("symbol"))

                min_order_size = Decimal(rule.get("quantity_min"))
                tick_size = Decimal(rule.get("price_increment"))
                step_size = Decimal(rule.get("quantity_increment"))
                min_notional = Decimal(rule.get("price_min"))

                retval.append(
                    TradingRule(trading_pair,
                                min_order_size=min_order_size,
                                min_price_increment=Decimal(tick_size),
                                min_base_amount_increment=Decimal(step_size),
                                min_notional_size=Decimal(min_notional)))

            except Exception:
                self.logger().exception(f"Error parsing the trading pair rule {rule.get('symbol')}. Skipping.")
        return retval

    async def _status_polling_loop_fetch_updates(self):
        await self._update_order_fills_from_trades()
        await super()._status_polling_loop_fetch_updates()

    async def _update_trading_fees(self):
        """
        Update fees information from the exchange
        """
        pass

    async def _user_stream_event_listener(self):
        """
        Foxbit has no this kind of event.
        """
        pass

    async def _update_order_fills_from_trades(self):
        """
        This is intended to be a backup measure to get filled events with trade ID for orders,
        NOTE: It is not required to copy this functionality in other connectors.
        This is separated from _update_order_status which only updates the order status without producing filled
        events, since Foxbit's get order endpoint does not return trade IDs.
        The minimum poll interval for order status is 10 seconds.
        """
        small_interval_last_tick = self._last_poll_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL
        small_interval_current_tick = self.current_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL
        long_interval_last_tick = self._last_poll_timestamp / self.LONG_POLL_INTERVAL
        long_interval_current_tick = self.current_timestamp / self.LONG_POLL_INTERVAL

        if (long_interval_current_tick > long_interval_last_tick
                or (self.in_flight_orders and small_interval_current_tick > small_interval_last_tick)):
            order_by_exchange_id_map = {}
            for order in self._order_tracker.all_orders.values():
                order_by_exchange_id_map[order.exchange_order_id] = order

            tasks = []
            trading_pairs = self.trading_pairs
            for trading_pair in trading_pairs:
                params = {
                    "market_symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
                }
                if self._last_poll_timestamp > 0:
                    params["start_time"] = (datetime.utcnow() - timedelta(minutes=self.SHORT_POLL_INTERVAL)).isoformat()[:23] + "Z"
                tasks.append(self._api_get(
                    path_url=CONSTANTS.MY_TRADES_PATH_URL,
                    params=params,
                    is_auth_required=True))

            self.logger().debug(f"Polling for order fills of {len(tasks)} trading pairs.")
            results = await safe_gather(*tasks, return_exceptions=True)

            for trades, trading_pair in zip(results, trading_pairs):

                if isinstance(trades, Exception):
                    self.logger().network(
                        f"Error fetching trades update for the order {trading_pair}: {trades}.",
                        app_warning_msg=f"Failed to fetch trade update for {trading_pair}."
                    )
                    continue
                for trade in trades['data']:
                    exchange_order_id = str(trade["order_id"])
                    if exchange_order_id in order_by_exchange_id_map:
                        # This is a fill for a tracked order
                        tracked_order = order_by_exchange_id_map[exchange_order_id]
                        fee = TradeFeeBase.new_spot_fee(
                            fee_schema=self.trade_fee_schema(),
                            trade_type=tracked_order.trade_type,
                            percent_token=trade["fee_currency_symbol"],
                            flat_fees=[TokenAmount(amount=Decimal(trade["fee"]), token=trade["fee_currency_symbol"])]
                        )
                        trade_update = TradeUpdate(
                            trade_id=str(trade["id"]),
                            client_order_id=tracked_order.client_order_id,
                            exchange_order_id=exchange_order_id,
                            trading_pair=trading_pair,
                            fee=fee,
                            fill_base_amount=Decimal(trade["quantity"]),
                            fill_quote_amount=Decimal(trade["quantity"]),
                            fill_price=Decimal(trade["price"]),
                            fill_timestamp=parser.parse(trade["created_at"]).timestamp(),
                        )
                        self._order_tracker.process_trade_update(trade_update)
                    elif self.is_confirmed_new_order_filled_event(str(trade["id"]), exchange_order_id, trading_pair):
                        # This is a fill of an order registered in the DB but not tracked any more
                        self._current_trade_fills.add(TradeFillOrderDetails(
                            market=self.display_name,
                            exchange_trade_id=str(trade["id"]),
                            symbol=trading_pair))
                        self.trigger_event(
                            MarketEvent.OrderFilled,
                            OrderFilledEvent(
                                timestamp=parser.parse(trade["created_at"]).timestamp(),
                                order_id=self._exchange_order_ids.get(str(trade["order_id"]), None),
                                trading_pair=trading_pair,
                                trade_type=TradeType.BUY if trade["side"] == "BUY" else TradeType.SELL,
                                order_type=OrderType.LIMIT,
                                price=Decimal(trade["price"]),
                                amount=Decimal(trade["quantity"]),
                                trade_fee=trade["fee"],
                            ),
                            exchange_trade_id=str(trade["id"])
                        )
                        self.logger().info(f"Recreating missing trade in TradeFill: {trade}")

    async def _update_order_status(self):
        # This is intended to be a backup measure to close straggler orders, in case Foxbit's user stream events
        # are not working.
        # The minimum poll interval for order status is 10 seconds.
        last_tick = self._last_poll_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL
        current_tick = self.current_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL

        tracked_orders: List[InFlightOrder] = list(self.in_flight_orders.values())
        if current_tick > last_tick and len(tracked_orders) > 0:

            tasks = [self._api_get(path_url=CONSTANTS.GET_ORDER_BY_ID.format(o.exchange_order_id),
                                   is_auth_required=True,
                                   limit_id=CONSTANTS.GET_ORDER_BY_ID) for o in tracked_orders]

            self.logger().debug(f"Polling for order status updates of {len(tasks)} orders.")
            results = await safe_gather(*tasks, return_exceptions=True)
            for order_update, tracked_order in zip(results, tracked_orders):
                client_order_id = tracked_order.client_order_id

                # If the order has already been canceled or has failed do nothing
                if client_order_id not in self.in_flight_orders:
                    continue

                if isinstance(order_update, Exception):
                    self.logger().network(
                        f"Error fetching status update for the order {client_order_id}: {order_update}.",
                        app_warning_msg=f"Failed to fetch status update for the order {client_order_id}."
                    )
                    # Wait until the order not found error have repeated a few times before actually treating
                    # it as failed. See: https://github.com/CoinAlpha/hummingbot/issues/601
                    await self._order_tracker.process_order_not_found(client_order_id)

                else:
                    # Update order execution status
                    new_state = CONSTANTS.ORDER_STATE[order_update["state"]]

                    update = OrderUpdate(
                        client_order_id=client_order_id,
                        exchange_order_id=str(order_update["id"]),
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=(datetime.now(timezone.utc).timestamp() * 1e3),
                        new_state=new_state,
                    )
                    self._order_tracker.process_order_update(update)

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        account_info = await self._api_get(
            path_url=CONSTANTS.ACCOUNTS_PATH_URL,
            is_auth_required=True)

        balances = account_info["data"]
        for balance_entry in balances:
            asset_name = balance_entry["currency_symbol"].upper()
            free_balance = Decimal(balance_entry["balance_available"])
            total_balance = Decimal(balance_entry["balance"])
            self._account_available_balances[asset_name] = free_balance
            self._account_balances[asset_name] = total_balance
            remote_asset_names.add(asset_name)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)
        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    async def _initialize_trading_pair_instrument_id_map(self):
        try:
            ws: WSAssistant = await self._create_web_assistants_factory().get_ws_assistant()
            await ws.connect(ws_url=web_utils.websocket_url(), ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL)

            auth_header = foxbit_utils.get_ws_message_frame(endpoint="GetInstruments",
                                                            msg_type=CONSTANTS.WS_MESSAGE_FRAME_TYPE["Request"],
                                                            payload={"OMSId": 1},)
            subscribe_request: WSJSONRequest = WSJSONRequest(payload=web_utils.format_ws_header(auth_header))

            await ws.send(subscribe_request)
            retValue: WSResponse = await ws.receive()
            if isinstance(type(retValue), type(WSResponse)):
                dec = json.JSONDecoder()
                exchange_info = dec.decode(retValue.data['o'])

            self._initialize_trading_pair_instrument_id_from_exchange_info(exchange_info=exchange_info)
        except Exception:
            self.logger().exception("There was an error requesting exchange info.")

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        if order.exchange_order_id is not None:
            exchange_order_id = int(order.exchange_order_id)
            trading_pair = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
            all_fills_response = await self._api_get(
                path_url=CONSTANTS.MY_TRADES_PATH_URL,
                params={
                    "market_symbol": trading_pair,
                    "order_id": exchange_order_id
                },
                is_auth_required=True
            )

            for trade in all_fills_response:
                exchange_order_id = str(trade["id"])
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent_token=trade["fee_currency_symbol"],
                    flat_fees=[TokenAmount(amount=Decimal(trade["fee"]), token=trade["fee_currency_symbol"])]
                )
                trade_update = TradeUpdate(
                    trade_id=str(trade["id"]),
                    client_order_id=order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=trading_pair,
                    fee=fee,
                    fill_base_amount=Decimal(trade["quantity"]),
                    fill_quote_amount=Decimal(trade["quantity"]),
                    fill_price=Decimal(trade["price"]),
                    fill_timestamp=parser.parse(trade["created_at"]).timestamp(),
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        updated_order_data = await self._api_get(
            path_url=CONSTANTS.GET_ORDER_BY_ID.format(tracked_order.exchange_order_id),
            is_auth_required=True,
            limit_id=CONSTANTS.GET_ORDER_BY_ID
        )

        new_state = CONSTANTS.ORDER_STATE[updated_order_data["state"]]

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(updated_order_data["id"]),
            trading_pair=tracked_order.trading_pair,
            update_timestamp=(datetime.now(timezone.utc).timestamp() * 1e3),
            new_state=new_state,
        )

        return order_update

    async def _get_last_traded_price(self, trading_pair: str) -> float:

        ixm_id = await self.exchange_instrument_id_associated_to_pair(trading_pair=trading_pair)

        ws: WSAssistant = await self._create_web_assistants_factory().get_ws_assistant()
        await ws.connect(ws_url=web_utils.websocket_url(), ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL)

        auth_header = foxbit_utils.get_ws_message_frame(endpoint=CONSTANTS.WS_SUBSCRIBE_TOB,
                                                        msg_type=CONSTANTS.WS_MESSAGE_FRAME_TYPE["Request"],
                                                        payload={"OMSId": 1, "InstrumentId": ixm_id},
                                                        )

        subscribe_request: WSJSONRequest = WSJSONRequest(payload=web_utils.format_ws_header(auth_header))

        await ws.send(subscribe_request)
        retValue: WSResponse = await ws.receive()
        if isinstance(type(retValue), type(WSResponse)):
            dec = json.JSONDecoder()
            data = dec.decode(retValue.data['o'])

            if not (len(data) and "LastTradedPx" in data):
                raise IOError(f"Error fetching last traded prices for {trading_pair}. Response: {data}.")

            return float(data["LastTradedPx"])

        return 0.0

    def _set_trading_pair_instrument_id_map(self, trading_pair_and_instrument_id_map: Optional[Mapping[str, str]]):
        """
        Method added to allow the pure Python subclasses to set the value of the map
        """
        self._trading_pair_instrument_id_map = trading_pair_and_instrument_id_map

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for symbol_data in filter(foxbit_utils.is_exchange_information_valid, exchange_info["data"]):
            mapping[symbol_data["symbol"]] = combine_to_hb_trading_pair(base=symbol_data['base']['symbol'].upper(),
                                                                        quote=symbol_data['quote']['symbol'].upper())
        self._set_trading_pair_symbol_map(mapping)

    def _initialize_trading_pair_instrument_id_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for symbol_data in filter(foxbit_utils.is_exchange_information_valid, exchange_info):
            mapping[symbol_data["InstrumentId"]] = combine_to_hb_trading_pair(symbol_data['Product1Symbol'].upper(),
                                                                              symbol_data['Product2Symbol'].upper())
        self._set_trading_pair_instrument_id_map(mapping)

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        error_description = str(request_exception)
        is_time_synchronizer_related = ("-1021" in error_description
                                        and "Timestamp for this request" in error_description)
        return is_time_synchronizer_related
