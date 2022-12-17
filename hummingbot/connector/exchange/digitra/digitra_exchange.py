import asyncio
import time
from decimal import Decimal
from functools import reduce
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
                 digitra_refresh_token: Optional[str] = None,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self._jwt = digitra_jwt
        self._refresh_token = digitra_refresh_token if digitra_refresh_token is not (None or '') else None
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        super().__init__(client_config_map)
        self.real_time_balance_update = False

    @property
    def authenticator(self) -> AuthBase:
        return DigitraAuth(
            jwt=self._jwt,
            refresh_token=self._refresh_token,
            domain=self._domain,
            time_provider=self._time_synchronizer)

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
        side = "BUY" if trade_type is TradeType.BUY else "SELL"
        _type = "MARKET" if order_type is OrderType.MARKET else "LIMIT"

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

        order_result = await self._api_post(
            path_url=CONSTANTS.API_ORDERS_PATH,
            data=api_params,
            is_auth_required=True,
            return_err=True,
            limit_id=CONSTANTS.RATE_SEND_ORDER)

        o_id = order_result["result"]["id"]
        transact_time = parser.isoparse(order_result["result"]["created_at"]).timestamp()

        return o_id, transact_time

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        exchange_order_id = tracked_order.exchange_order_id

        try:
            cancel_result = await self._api_delete(
                path_url=CONSTANTS.API_ORDER_PATH.format(order_id=exchange_order_id),
                is_auth_required=True,
                return_err=True,
                limit_id=CONSTANTS.RATE_CANCEL_ORDER)

            if "errors" in cancel_result:
                cancelled = False
                for err in cancel_result["errors"]:
                    if err["field"] == "status" and err["msg"] == "Order can't be cancelled while in status CANCELED":
                        cancelled = True
                        break

                if not cancelled:
                    raise Exception(cancel_result["errors"])
                else:
                    order_status: OrderUpdate = OrderUpdate(
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=tracked_order.last_update_timestamp,
                        new_state=OrderState.CANCELED,
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=tracked_order.exchange_order_id,
                    )
                    await self._order_tracker.process_order_update(order_status)
                    return True

            cancel_result = cancel_result["result"]

            if "code" in cancel_result and cancel_result["code"] == 404:
                await self._order_tracker.process_order_not_found(tracked_order.client_order_id)
                return True

            order_status: OrderUpdate = OrderUpdate(
                trading_pair=tracked_order.trading_pair,
                update_timestamp=parser.isoparse(cancel_result["updated_at"]).timestamp(),
                new_state=CONSTANTS.ORDER_STATE_MAPPING[cancel_result["status"]],
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=tracked_order.exchange_order_id,
            )

            await self._order_tracker.process_order_update(order_status)

            return order_status.new_state in [OrderState.CANCELED, OrderState.PENDING_CANCEL]
        except Exception as e:
            self.logger().error(e)
            return False

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        trading_pair_rules = exchange_info_dict.get("result", [])
        retval = []
        for rule in filter(digitra_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("id"))

                trading_rule = TradingRule(
                    trading_pair,
                    min_order_size=Decimal(str(rule.get("minimum_order_size"))),
                    min_price_increment=Decimal(str(rule.get("price_increment_size"))),
                    min_base_amount_increment=Decimal(str(rule.get("increment_size"))),
                )

                retval.append(trading_rule)

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
                        in_flight_order = next(
                            value
                            for value in self._order_tracker.all_fillable_orders.values() if
                            value.exchange_order_id == data['id']
                        ) if len(self._order_tracker.all_fillable_orders.values()) > 0 else None

                        if in_flight_order is None:
                            self.logger().warning("Received order udpate for not tracked order", data)
                        else:
                            current_filled = Decimal(str(data["filledSize"]))
                            in_flight_filled = reduce(lambda acc, v: acc + v.fill_base_amount,
                                                      in_flight_order.order_fills.values(), 0)

                            missing_filled = current_filled - in_flight_filled

                            if missing_filled > 0:
                                fee = TradeFeeBase.new_spot_fee(
                                    fee_schema=self.trade_fee_schema(),
                                    trade_type=in_flight_order.trade_type,
                                    percent=Decimal(0)
                                )

                                trade_update = TradeUpdate(
                                    # TODO Replace with trade info once trade is available
                                    trade_id=f"{data['id']}-{int(time.time())}",
                                    client_order_id=in_flight_order.client_order_id,
                                    exchange_order_id=str(data["id"]),
                                    trading_pair=in_flight_order.trading_pair,
                                    fee=fee,
                                    fill_base_amount=Decimal(str(data["filledSize"])),
                                    # TODO Revise this
                                    fill_quote_amount=Decimal(str(data["filledSize"])) * Decimal(
                                        str(data["avgFillPrice"])),
                                    fill_price=Decimal(str(data["avgFillPrice"])),
                                    fill_timestamp=parser.isoparse(data["createdAt"]).timestamp()
                                )
                                self._order_tracker.process_trade_update(trade_update)

                            order_update = OrderUpdate(
                                trading_pair=in_flight_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=CONSTANTS.ORDER_STATE_MAPPING[data["status"]],
                                client_order_id=in_flight_order.client_order_id,
                                exchange_order_id=str(data["id"])
                            )
                            await self._order_tracker.process_order_update(order_update)

                # TODO Process balance events once they are available through websocket
                # NOTE While websocket does not provide real time updates, 'self.real_time_balance_update' helps with
                # fetching balances through api in real time

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        # TODO Use real trades endpoint once available
        # NOTE We are deriving fake trades com order state based on difference of filled size

        trade_updates = []

        if order.exchange_order_id is not None:
            order_status = None
            try:
                order_status = await self._api_get(
                    path_url=CONSTANTS.API_ORDER_PATH.format(order_id=order.exchange_order_id),
                    is_auth_required=True,
                    limit_id=CONSTANTS.RATE_SHARED_LIMITER
                )
            except Exception:
                if order_status and "msg" in order_status and order_status["msg"] == "Not found":
                    await self._order_tracker.process_order_not_found(order.client_order_id)
                    return []
                else:
                    self.logger().error("Failed to get order status", exc_info=True)
                    raise

            order_status = order_status["result"]

            in_flight_filled = reduce(lambda acc, v: acc + v.fill_base_amount, order.order_fills.values(), 0)
            current_filled = Decimal(str(order_status["filled"]))

            missing_filled = current_filled - in_flight_filled
            if missing_filled > 0:
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent=Decimal(order_status["fee"])
                )

                trade_update = TradeUpdate(
                    # TODO Get real trade id once available
                    trade_id=f"{order_status['id']}-{int(time.time())}",
                    client_order_id=order_status["custom_id"],
                    exchange_order_id=order.exchange_order_id,
                    trading_pair=order.trading_pair,
                    fee=fee,
                    fill_base_amount=missing_filled,
                    # TODO Revise this
                    fill_quote_amount=Decimal(missing_filled) * Decimal(str(order_status["filled_weighted_price"])),
                    fill_price=Decimal(str(order_status["filled_weighted_price"])),
                    fill_timestamp=parser.isoparse(order_status["updated_at"]).timestamp()
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:

        if tracked_order.exchange_order_id is None:
            return OrderUpdate(
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=None,
                trading_pair=tracked_order.trading_pair,
                update_timestamp=tracked_order.creation_timestamp,
                new_state=OrderState.FAILED
            )

        order_status = None
        try:
            order_status = await self._api_get(
                path_url=CONSTANTS.API_ORDER_PATH.format(order_id=tracked_order.exchange_order_id),
                is_auth_required=True,
                limit_id=CONSTANTS.RATE_SHARED_LIMITER
            )
        except Exception as e:
            if order_status and "msg" in order_status and order_status["msg"] == "Not found":
                await self._order_tracker.process_order_not_found(tracked_order.client_order_id)
                return OrderUpdate(
                    client_order_id=tracked_order.client_order_id,
                    exchange_order_id=None,
                    trading_pair=tracked_order.trading_pair,
                    update_timestamp=tracked_order.creation_timestamp,
                    new_state=OrderState.FAILED
                )
            else:
                self.logger().error(e)
                raise

        order_status = order_status["result"]

        new_state = CONSTANTS.ORDER_STATE_MAPPING[order_status["status"]]

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=tracked_order.exchange_order_id,
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
                is_auth_required=True,
                limit_id=CONSTANTS.RATE_SHARED_LIMITER
            )
        except Exception as e:
            self.logger().error(e)
            raise e

        balances = result["result"]
        for balance_entry in balances:
            asset_name = balance_entry["asset"]
            free_balance = Decimal(str(balance_entry["amount"]))
            total_balance = Decimal(str(balance_entry["amount"])) + Decimal(str(balance_entry["amount_trading"]))
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
        return await DigitraAPIOrderBookDataSource.get_last_traded_prices(trading_pairs=trading_pairs, domain=domain)
