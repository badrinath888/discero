from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
from typing import Any

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import (
    LinkTokenCreateRequestUser,
)
from plaid.model.products import Products
from plaid.model.transactions_sync_request import (
    TransactionsSyncRequest,
)

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class PlaidConfigurationError(RuntimeError):
    pass


class PlaidServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        reconnect_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.reconnect_required = reconnect_required


@dataclass(frozen=True)
class PlaidExchangeResult:
    access_token: str
    item_id: str


@dataclass(frozen=True)
class PlaidAccountData:
    provider_account_id: str
    name: str
    official_name: str | None
    account_type: str
    account_subtype: str | None
    mask: str | None
    current_balance_cents: int | None
    available_balance_cents: int | None
    currency: str


def get_plaid_client(
    app_settings: Settings = settings,
) -> plaid_api.PlaidApi:
    if not app_settings.plaid_is_configured:
        raise PlaidConfigurationError(
            "Plaid credentials are not configured"
        )

    environments = {
        "sandbox": plaid.Environment.Sandbox,
        "production": plaid.Environment.Production,
    }

    configuration = plaid.Configuration(
        host=environments[app_settings.plaid_env],
        api_key={
            "clientId": app_settings.plaid_client_id,
            "secret": app_settings.plaid_secret,
        },
    )

    return plaid_api.PlaidApi(
        plaid.ApiClient(configuration)
    )


def create_link_token(
    user_id: int,
    app_settings: Settings = settings,
) -> str:
    client = get_plaid_client(app_settings)

    request_data: dict[str, object] = {
        "products": [
            Products(product)
            for product in app_settings.plaid_product_list
        ],
        "client_name": app_settings.app_name,
        "country_codes": [
            CountryCode(code)
            for code in app_settings.plaid_country_code_list
        ],
        "language": "en",
        "user": LinkTokenCreateRequestUser(
            client_user_id=str(user_id)
        ),
    }

    if app_settings.plaid_redirect_uri:
        request_data["redirect_uri"] = (
            app_settings.plaid_redirect_uri
        )

    try:
        response = client.link_token_create(
            LinkTokenCreateRequest(**request_data)
        )
    except plaid.ApiException as exc:
        logger.exception(
            "Plaid link token creation failed: status=%s body=%s",
            getattr(exc, "status", None),
            getattr(exc, "body", None),
        )
        raise PlaidServiceError(
            "Unable to create Plaid Link token"
        ) from exc

    return response["link_token"]


def exchange_public_token(
    public_token: str,
    app_settings: Settings = settings,
) -> PlaidExchangeResult:
    if not public_token.strip():
        raise PlaidServiceError(
            "Plaid public token cannot be empty"
        )

    client = get_plaid_client(app_settings)

    try:
        response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(
                public_token=public_token.strip()
            )
        )
    except plaid.ApiException as exc:
        raise PlaidServiceError(
            "Unable to exchange Plaid public token"
        ) from exc

    return PlaidExchangeResult(
        access_token=response["access_token"],
        item_id=response["item_id"],
    )


def remove_item(
    access_token: str,
    app_settings: Settings = settings,
) -> None:
    if not access_token:
        raise PlaidServiceError(
            "Plaid access token cannot be empty"
        )

    client = get_plaid_client(app_settings)

    try:
        client.item_remove(
            ItemRemoveRequest(
                access_token=access_token
            )
        )
    except plaid.ApiException as exc:
        raise PlaidServiceError(
            "Unable to disconnect Plaid institution"
        ) from exc


def get_accounts(
    access_token: str,
    app_settings: Settings = settings,
) -> list[PlaidAccountData]:
    if not access_token:
        raise PlaidServiceError(
            "Plaid access token cannot be empty"
        )

    client = get_plaid_client(app_settings)

    try:
        response = client.accounts_get(
            AccountsGetRequest(
                access_token=access_token
            )
        )
    except plaid.ApiException as exc:
        reconnect_required = (
            _plaid_error_code(exc) == "ITEM_LOGIN_REQUIRED"
        )
        raise PlaidServiceError(
            "This institution needs to be reconnected"
            if reconnect_required
            else "Unable to retrieve Plaid accounts",
            reconnect_required=reconnect_required,
        ) from exc

    return [
        _account_from_plaid(account)
        for account in response["accounts"]
    ]


def decimal_to_cents(
    value: Decimal | float | int | str | None,
) -> int | None:
    if value is None:
        return None

    decimal_value = Decimal(str(value))

    return int(
        (decimal_value * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _account_from_plaid(
    account: Any,
) -> PlaidAccountData:
    balances = account["balances"]

    return PlaidAccountData(
        provider_account_id=account["account_id"],
        name=account["name"],
        official_name=account.get("official_name"),
        account_type=_enum_value(account["type"]),
        account_subtype=_optional_enum_value(
            account.get("subtype")
        ),
        mask=account.get("mask"),
        current_balance_cents=decimal_to_cents(
            balances.get("current")
        ),
        available_balance_cents=decimal_to_cents(
            balances.get("available")
        ),
        currency=(
            balances.get("iso_currency_code")
            or "USD"
        ).upper(),
    )


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _optional_enum_value(
    value: Any,
) -> str | None:
    if value is None:
        return None

    return _enum_value(value)

@dataclass(frozen=True)
class PlaidTransactionData:
    provider_transaction_id: str
    provider_account_id: str
    posted_on: date
    description: str
    merchant_name: str | None
    amount_cents: int
    category: str
    pending: bool


@dataclass(frozen=True)
class PlaidTransactionSyncResult:
    added: list[PlaidTransactionData]
    modified: list[PlaidTransactionData]
    removed: list[str]
    next_cursor: str


def sync_transactions(
    access_token: str,
    cursor: str | None = None,
    app_settings: Settings = settings,
) -> PlaidTransactionSyncResult:
    if not access_token:
        raise PlaidServiceError(
            "Plaid access token cannot be empty"
        )

    original_cursor = cursor

    for attempt in range(3):
        try:
            return _sync_transaction_pages(
                access_token=access_token,
                cursor=original_cursor,
                app_settings=app_settings,
            )
        except plaid.ApiException as exc:
            if (
                _plaid_error_code(exc)
                == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
                and attempt < 2
            ):
                continue

            reconnect_required = (
                _plaid_error_code(exc) == "ITEM_LOGIN_REQUIRED"
            )
            raise PlaidServiceError(
                "This institution needs to be reconnected"
                if reconnect_required
                else "Unable to synchronize Plaid transactions",
                reconnect_required=reconnect_required,
            ) from exc

    raise PlaidServiceError(
        "Unable to synchronize Plaid transactions"
    )


def _sync_transaction_pages(
    access_token: str,
    cursor: str | None,
    app_settings: Settings,
) -> PlaidTransactionSyncResult:
    client = get_plaid_client(app_settings)

    added: list[PlaidTransactionData] = []
    modified: list[PlaidTransactionData] = []
    removed: list[str] = []

    next_cursor = cursor
    has_more = True

    while has_more:
        request_data: dict[str, object] = {
            "access_token": access_token,
        }

        if next_cursor is not None:
            request_data["cursor"] = next_cursor

        response = client.transactions_sync(
            TransactionsSyncRequest(**request_data)
        )

        added.extend(
            _transaction_from_plaid(transaction)
            for transaction in response["added"]
        )

        modified.extend(
            _transaction_from_plaid(transaction)
            for transaction in response["modified"]
        )

        removed.extend(
            removed_transaction["transaction_id"]
            for removed_transaction in response["removed"]
        )

        next_cursor = response["next_cursor"]
        has_more = response["has_more"]

    return PlaidTransactionSyncResult(
        added=added,
        modified=modified,
        removed=removed,
        next_cursor=next_cursor or "",
    )


def _transaction_from_plaid(
    transaction: Any,
) -> PlaidTransactionData:
    amount_cents = decimal_to_cents(
        transaction["amount"]
    )

    if amount_cents is None:
        raise PlaidServiceError(
            "Plaid transaction amount is missing"
        )

    merchant_name = _clean_optional_text(
        transaction.get("merchant_name")
    )

    description = (
        merchant_name
        or _clean_optional_text(transaction.get("name"))
        or "Plaid transaction"
    )

    return PlaidTransactionData(
        provider_transaction_id=transaction[
            "transaction_id"
        ],
        provider_account_id=transaction["account_id"],
        posted_on=_transaction_date(transaction["date"]),
        description=description[:512],
        merchant_name=(
            merchant_name[:255]
            if merchant_name
            else None
        ),
        amount_cents=-amount_cents,
        category=_transaction_category(transaction),
        pending=bool(transaction.get("pending", False)),
    )


def _transaction_date(value: Any) -> date:
    if isinstance(value, date):
        return value

    return date.fromisoformat(str(value))


def _transaction_category(transaction: Any) -> str:
    finance_category = transaction.get(
        "personal_finance_category"
    )

    if not finance_category:
        return "Uncategorized"

    primary = finance_category.get("primary")

    if primary is None:
        return "Uncategorized"

    category_map = {
        "FOOD_AND_DRINK": "Dining",
        "GENERAL_MERCHANDISE": "Shopping",
        "GENERAL_SERVICES": "Utilities",
        "GOVERNMENT_AND_NON_PROFIT": "Utilities",
        "HOME_IMPROVEMENT": "Housing",
        "INCOME": "Income",
        "LOAN_PAYMENTS": "Housing",
        "MEDICAL": "Health",
        "PERSONAL_CARE": "Health",
        "RENT_AND_UTILITIES": "Housing",
        "TRANSPORTATION": "Transport",
        "TRAVEL": "Transport",
    }

    return category_map.get(
        _enum_value(primary),
        "Uncategorized",
    )


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    return cleaned or None


def _plaid_error_code(exc: plaid.ApiException) -> str | None:
    try:
        body = json.loads(exc.body or "{}")
    except (TypeError, json.JSONDecodeError):
        return None

    error_code = body.get("error_code")

    return str(error_code) if error_code else None
