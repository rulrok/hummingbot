from typing import Dict, Optional

from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class DigitraOrderBook(OrderBook):

    @classmethod
    def snapshot_message_from_exchange_rest(cls,
                                            msg: Dict[str, any],
                                            timestamp: float,
                                            metadata: Optional[Dict] = None) -> OrderBookMessage:
        """
        Creates a snapshot message with the order book snapshot message
        :param msg: the response from the exchange when requesting the order book snapshot
        :param timestamp: the snapshot timestamp
        :param metadata: a dictionary with extra information to add to the snapshot data
        :return: a snapshot message with the snapshot information received from the exchange
        """
        if metadata:
            msg.update(metadata)

        return OrderBookMessage(message_type=OrderBookMessageType.SNAPSHOT, content={
            "trading_pair": msg["id"],
            "update_id": timestamp,
            "bids": [(bid["price"], bid["size"]) for bid in msg["order_book"]["bids"]],
            "asks": [(ask["price"], ask["size"]) for ask in msg["order_book"]["asks"]]
        }, timestamp=timestamp)
