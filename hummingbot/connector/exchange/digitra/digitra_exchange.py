import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from dateutil import parser

from hummingbot.connector.exchange.digitra import (
    digitra_constants as CONSTANTS,
    digitra_utils,
    digitra_web_utils as web_utils,
)
from hummingbot.connector.exchange.digitra.digitra_api_order_book_data_source import DigitraAPIOrderBookDataSource
from hummingbot.connector.exchange.digitra.digitra_api_user_stream_data_source import DigitraAPIUserStreamDataSource
from hummingbot.connector.exchange.digitra.digitra_auth import DigitraAuth
from hummingbot.connector.exchange_base import bidict
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter

s_logger = None


class DigitraExchange(ExchangePyBase):
    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 digitra_jwt: str,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.api_jwt = digitra_jwt
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        super().__init__(client_config_map)
        self.real_time_balance_update = False

    @property
    def authenticator(self) -> AuthBase:
        return DigitraAuth(jwt=self.api_jwt, time_provider=self._time_synchronizer)

    @property
    def name(self) -> str:
        return self.domain

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        return 25

    @property
    def client_order_id_prefix(self) -> str:
        return "HB_"

    @property
    def trading_rules_request_path(self) -> str:
        return CONSTANTS.API_ALL_MARKETS_PATH

    @property
    def trading_pairs_request_path(self) -> str:
        return CONSTANTS.API_ALL_MARKETS_PATH

    @property
    def check_network_request_path(self) -> str:
        return CONSTANTS.API_HEALTH_CHECK_PATH

    @property
    def trading_pairs(self) -> List[str]:
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self) -> List[OrderType]:
        return [OrderType.LIMIT, OrderType.MARKET]

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        return False

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self.domain,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return DigitraAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            domain=self.domain,
            api_factory=self._web_assistants_factory
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:

        return DigitraAPIUserStreamDataSource(
            auth=self._auth,
            domain=self.domain,
            api_factory=self._web_assistants_factory,
        )

    def _get_fee(self, base_currency: str, quote_currency: str, order_type: OrderType, order_side: TradeType,
                 amount: Decimal, price: Decimal = 0,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:

        # Note it must either return 'DeductedFromReturnsTradeFee' or 'AddedToCostTradeFee' to comply with signature

        # Zero fee
        return AddedToCostTradeFee(
            percent=Decimal(0)
        )

    async def _place_order(
            self,
            order_id: str,
            trading_pair: str,
            amount: Decimal,
            trade_type: TradeType,
            order_type: OrderType,
            price: Decimal,
            **kwargs
    ) -> Tuple[str, float]:

        market = await self.trading_pair_associated_to_exchange_symbol(symbol=trading_pair)
        side = "BUY" if trade_type is TradeType.BUY else TradeType.SELL
        _type = "MARKET" if order_type is OrderType.MARKET else OrderType.LIMIT
        amount_str = f"{amount:f}"
        price_str = f"{price:f}"

        api_params = {
            "custom_id": order_id,
            "market": market,
            "side": side,
            "type": _type,
            "price": price_str,
            "size": amount_str
        }

        if order_type == OrderType.LIMIT:
            api_params["time_in_force"] = "GTC"

        raise Exception("TODO Test this method properly")

        # order_result = await self._api_post(
        #     path_url=CONSTANTS.API_ORDERS,
        #     data=api_params,
        #     is_auth_required=True)
        #
        # o_id = order_result["id"]
        # transact_time = parser.isoparse(order_result["created_at"]).timestamp()
        #
        # return o_id, transact_time

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        exchange_order_id = tracked_order.exchange_order_id

        try:
            cancel_result = await self._api_delete(
                path_url=CONSTANTS.API_ORDER_PATH.format(order_id=exchange_order_id),
                is_auth_required=True)

            cancel_result = cancel_result["result"]

            order_status: OrderUpdate = OrderUpdate(
                trading_pair=tracked_order.trading_pair,
                update_timestamp=tracked_order.last_update_timestamp,
                new_state=OrderState.PENDING_CANCEL
                if cancel_result["status"] == "PENDING_CANCELING"
                else OrderState.CANCELED,  # TODO Revise this
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=tracked_order.exchange_order_id,
            )

            self._order_tracker.process_order_update(order_status)
        except Exception as e:
            # TODO Handle exception
            self.logger().error(e)
            return False

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        trading_pair_rules = exchange_info_dict.get("result", [])
        retval = []
        for rule in filter(digitra_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("id"))

                min_order_size = Decimal(rule.get("minimum_order_size"))
                tick_size = rule.get("price_increment_size")
                step_size = Decimal(rule.get("increment_size"))
                min_notional = Decimal(rule.get("minimum_order_size"))

                retval.append(
                    # TODO Revise if params are correct
                    TradingRule(trading_pair,
                                min_order_size=min_order_size,
                                min_price_increment=Decimal(tick_size),
                                min_base_amount_increment=Decimal(step_size),
                                min_notional_size=Decimal(min_notional)))

            except Exception:
                self.logger().exception(f"Error parsing the trading pair rule {rule}. Skipping.")
        return retval

    async def _update_trading_fees(self):
        """
        Update fees information from the exchange
        """
        pass

    async def _user_stream_event_listener(self):
        async for event_message in self._iter_user_event_queue():
            try:
                _type = event_message.get("type")
                data = event_message.get("data")
                channel = event_message.get("channel")

                if _type == "update":
                    if channel == "orders":
                        # TODO Either derive trades from order state progression or use proper trades endpoint once available
                        # NOTE Using a naive approach of considering FILLED orders as single trade events
                        client_order_id = event_message.get("clientId")

                        if CONSTANTS.ORDER_STATE_MAPPING[data["status"]] == OrderState.FILLED:
                            tracked_order = self._order_tracker.all_fillable_orders.get(client_order_id)
                            if tracked_order is not None:
                                fee = TradeFeeBase.new_spot_fee(
                                    fee_schema=self.trade_fee_schema(),
                                    trade_type=tracked_order.trade_type,
                                    percent=Decimal(0)
                                )

                                trade_update = TradeUpdate(
                                    trade_id=str(data["id"]),  # TODO Replace with trade info once trade is available
                                    client_order_id=client_order_id,
                                    exchange_order_id=str(data["id"]),
                                    trading_pair=tracked_order.trading_pair,
                                    fee=fee,
                                    fill_base_amount=Decimal(data["size"]),
                                    # TODO Revise this
                                    fill_quote_amount=Decimal(data["size"] * data["avgFillPrice"]),
                                    fill_price=Decimal(data["avgFillPrice"]),
                                    fill_timestamp=parser.isoparse(data["createdAt"]).timestamp()
                                )
                                self._order_tracker.process_trade_update(trade_update)

                        tracked_order = self._order_tracker.all_updatable_orders.get(client_order_id)
                        if tracked_order is not None:
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=parser.isoparse(data["createdAt"]).timestamp(),
                                new_state=CONSTANTS.ORDER_STATE_MAPPING[data["status"]],
                                client_order_id=client_order_id,
                                exchange_order_id=str(data["id"])
                            )
                            self._order_tracker.process_order_update(order_update)

                # TODO Process balance events once they are available through websocket
                # NOTE While websocket does not provide real time updates, 'self.real_time_balance_update' helps with
                # fetching balances through api in real time

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        # TODO Either derive trades from order state progression or use proper trades endpoint once available
        # NOTE Using a naive approach of considering FILLED orders as single trade events

        trade_updates = []

        if order.exchange_order_id is not None:
            order_status = await self._api_get(
                path_url=CONSTANTS.API_ORDER_PATH.format(order_id=order.exchange_order_id)
            )

            order_status = order_status["result"]

            if CONSTANTS.ORDER_STATE_MAPPING[order_status["status"]] == OrderState.FILLED:
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent=Decimal(order_status["fee"])
                )

                trade_update = TradeUpdate(
                    trade_id=order_status["id"],
                    client_order_id=order_status["custom_id"],
                    exchange_order_id=order.exchange_order_id,
                    trading_pair=order.trading_pair,
                    fee=fee,
                    fill_base_amount=Decimal(order_status["size"]),
                    # TODO Revise this
                    fill_quote_amount=Decimal(order_status["size"] * order_status["filled_weighted_price"]),
                    fill_price=Decimal(order_status["filled_weighted_price"]),
                    fill_timestamp=parser.isoparse(order_status["updated_at"]).timestamp()
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:

        order_status = await self._api_get(
            path_url=CONSTANTS.API_ORDER_PATH.format(order_id=tracked_order.exchange_order_id)
        )

        new_state = CONSTANTS[order_status["status"]]

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=order_status["id"],
            trading_pair=tracked_order.trading_pair,
            update_timestamp=parser.isoparse(order_status["updated_at"]).timestamp(),
            new_state=new_state
        )

        return order_update

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        try:
            result = await self._api_request(
                CONSTANTS.API_BALANCES_PATH,
                RESTMethod.GET,
                is_auth_required=True
            )
        except Exception as e:
            self.logger().error(e)
            raise e

        balances = result["result"]
        for balance_entry in balances:
            asset_name = balance_entry["asset"]
            free_balance = Decimal(balance_entry["amount"])
            total_balance = Decimal(balance_entry["amount"]) + Decimal(balance_entry["amount_trading"])
            self._account_available_balances[asset_name] = free_balance
            self._account_balances[asset_name] = total_balance
            remote_asset_names.add(asset_name)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)
        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for symbol_data in filter(digitra_utils.is_exchange_information_valid, exchange_info["result"]):
            mapping[symbol_data["id"]] = combine_to_hb_trading_pair(base=symbol_data["base_currency"],
                                                                    quote=symbol_data["quote_currency"])
        self._set_trading_pair_symbol_map(mapping)

    async def get_last_traded_prices(self, trading_pairs: List[str], domain: Optional[str] = None) -> Dict[str, float]:
        return DigitraAPIOrderBookDataSource.get_last_traded_prices(trading_pairs, domain)
