from decimal import Decimal

from pydantic import Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap, ClientFieldData
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

CENTRALIZED = True

EXAMPLE_PAIR = "BTC-BRL"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.000"),
    taker_percent_fee_decimal=Decimal("0.000"),
)


class DigitraConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="digitra", const=True, client_data=None)
    # digitra_api_key: SecretStr = Field(
    #     default=...,
    #     client_data=ClientFieldData(
    #         prompt=lambda cm: "Enter your Digitra API key",
    #         is_secure=True,
    #         is_connect_key=True,
    #         prompt_on_new=True,
    #     ),
    # )
    # digitra_api_secret: SecretStr = Field(
    #     default=...,
    #     client_data=ClientFieldData(
    #         prompt=lambda cm: "Enter your Digitra API secret",
    #         is_secure=True,
    #         is_connect_key=True,
    #         prompt_on_new=True,
    #     ),
    # )
    digitra_jwt: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Digitra JWT auth token",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )

    class Config:
        title = "digitra"


KEYS = DigitraConfigMap.construct()

OTHER_DOMAINS = ["digitra_testnet"]
OTHER_DOMAINS_PARAMETER = {"digitra_testnet": "stg-hb.cloud"}
OTHER_DOMAINS_EXAMPLE_PAIR = {"digitra_testnet": "BTC-BRL"}
OTHER_DOMAINS_DEFAULT_FEES = {"digitra_testnet": DEFAULT_FEES}


class DigitraTestnetConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="digitra_testnet", const=True, client_data=None)
    # digitra_testnet_api_key: SecretStr = Field(
    #     default=...,
    #     client_data=ClientFieldData(
    #         prompt=lambda cm: "Enter your Digitra Testnet API Key",
    #         is_secure=True,
    #         is_connect_key=True,
    #         prompt_on_new=True,
    #     ),
    # )
    # digitra_testnet_api_secret: SecretStr = Field(
    #     default=...,
    #     client_data=ClientFieldData(
    #         prompt=lambda cm: "Enter your Digitra Testnet API secret",
    #         is_secure=True,
    #         is_connect_key=True,
    #         prompt_on_new=True,
    #     )
    # )
    digitra_testnet_jwt: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Digitra DEV JWT auth token",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )

    class Config:
        title = "digitra_testnet"


OTHER_DOMAINS_KEYS = {"digitra_testnet": DigitraTestnetConfigMap.construct()}
