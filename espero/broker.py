"""Broker adapters. One interface, two implementations, and a safety wrapper.

Live orders are the only code in this repo that can lose money, so:

* the credential is read from the environment, never from a file we commit
* every order carries a client_order_id generated before the call, so a retry
  can be deduplicated instead of doubling the position
* DryRunBroker wraps a real broker and refuses to send anything
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol


class BrokerError(RuntimeError):
    pass


@dataclass
class Ack:
    order_id: str
    client_id: str
    status: str
    filled_px: Optional[float] = None
    filled_size: Optional[float] = None
    fee: float = 0.0
    raw: Optional[dict] = None


def new_client_id(prefix: str = "esp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


class Broker(Protocol):
    name: str
    live: bool

    def price(self, product: str) -> float: ...
    def balance(self, currency: str) -> float: ...
    def market_buy(self, product: str, notional: float, client_id: str) -> Ack: ...
    def market_sell(self, product: str, size: float, client_id: str) -> Ack: ...


class CoinbaseBroker:
    """Coinbase Advanced Trade (the current API, not the retired Pro one).

    Needs a CDP key pair: COINBASE_API_KEY (the key name) and
    COINBASE_API_SECRET (the EC private key PEM). The official SDK handles the
    JWT signing; if it is not installed, construction fails loudly.
    """

    name = "coinbase-advanced"
    live = True

    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise BrokerError("COINBASE_API_KEY / COINBASE_API_SECRET are not set")
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = None

    def client(self):
        if self._client is None:
            try:
                from coinbase.rest import RESTClient
            except ImportError as exc:  # pragma: no cover
                raise BrokerError(
                    "pip install coinbase-advanced-py to trade on Coinbase"
                ) from exc
            self._client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)
        return self._client

    def price(self, product: str) -> float:
        data = self.client().get_product(product_id=product)
        px = data.get("price") if isinstance(data, dict) else None
        if px is None:
            raise BrokerError(f"no price for {product}: {data}")
        return float(px)

    def balance(self, currency: str) -> float:
        data = self.client().get_accounts()
        for account in data.get("accounts", []):
            if account.get("currency") == currency:
                return float((account.get("available_balance") or {}).get("value", 0))
        return 0.0

    def _parse(self, result: dict, client_id: str) -> Ack:
        if not result.get("success", False):
            raise BrokerError(f"order rejected: {result.get('error_response') or result}")
        order_id = result.get("order_id") or (result.get("success_response") or {}).get("order_id")
        return Ack(order_id=order_id or "", client_id=client_id, status="submitted", raw=result)

    def market_buy(self, product: str, notional: float, client_id: str) -> Ack:
        result = self.client().market_order_buy(
            client_order_id=client_id, product_id=product, quote_size=f"{notional:.2f}"
        )
        return self._parse(result, client_id)

    def market_sell(self, product: str, size: float, client_id: str) -> Ack:
        result = self.client().market_order_sell(
            client_order_id=client_id, product_id=product, base_size=f"{size:.8f}"
        )
        return self._parse(result, client_id)

    def open_orders(self, product: str) -> list:
        data = self.client().list_orders(product_id=product, order_status="OPEN")
        return data.get("orders", [])


class DryRunBroker:
    """Wraps a real broker, reads from it, and never sends an order."""

    live = False

    def __init__(self, inner: Broker):
        self.inner = inner
        self.name = f"dry-run({inner.name})"
        self.placed: list[Ack] = []

    def price(self, product: str) -> float:
        return self.inner.price(product)

    def balance(self, currency: str) -> float:
        return self.inner.balance(currency)

    def market_buy(self, product: str, notional: float, client_id: str) -> Ack:
        ack = Ack(order_id="dry", client_id=client_id, status="dry-run",
                  filled_px=self.inner.price(product), filled_size=notional / self.inner.price(product))
        self.placed.append(ack)
        return ack

    def market_sell(self, product: str, size: float, client_id: str) -> Ack:
        ack = Ack(order_id="dry", client_id=client_id, status="dry-run",
                  filled_px=self.inner.price(product), filled_size=size)
        self.placed.append(ack)
        return ack

    def open_orders(self, product: str) -> list:
        return []


def load_env(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    p = os.path.join(os.getcwd(), path)
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _secret() -> str:
    path = os.environ.get("COINBASE_API_SECRET_FILE", "")
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return os.environ.get("COINBASE_API_SECRET", "").replace("\\n", "\n")


def broker_from_env(dry_run: bool = True) -> Broker:
    """Build the broker the environment describes. Live requires a second opt-in."""
    load_env()
    key = os.environ.get("COINBASE_API_KEY", "")
    secret = _secret()
    if not key or not secret:
        raise BrokerError(
            "no credentials: put COINBASE_API_KEY and COINBASE_API_SECRET in .env "
            "(see .env.example)"
        )
    inner = CoinbaseBroker(key, secret)
    if dry_run:
        return DryRunBroker(inner)
    if os.environ.get("ESPERO_ALLOW_LIVE") != "1":
        raise BrokerError(
            "refusing to trade live: set ESPERO_ALLOW_LIVE=1 and pass --confirm-live"
        )
    return inner
