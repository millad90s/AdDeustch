"""Minimal PayPal REST integration for one-off token purchases.

Configured via env:
  PAYPAL_CLIENT_ID  - REST app client id
  PAYPAL_SECRET     - REST app secret
  PAYPAL_ENV        - "sandbox" (default) or "live"

If client id / secret are missing the feature is simply disabled (enabled() ->
False) and the buy UI is hidden. We create and capture orders server-side so the
charged amount is never trusted from the browser.
"""
import os
import httpx

def _client_id():
    return os.getenv("PAYPAL_CLIENT_ID", "")

def _secret():
    return os.getenv("PAYPAL_SECRET", "")

def _base():
    env = os.getenv("PAYPAL_ENV", "sandbox").lower()
    return "https://api-m.paypal.com" if env == "live" else "https://api-m.sandbox.paypal.com"

def enabled():
    return bool(_client_id() and _secret())

def client_id():
    return _client_id()


def _token():
    r = httpx.post(
        _base() + "/v1/oauth2/token",
        auth=(_client_id(), _secret()),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_order(amount_str, currency, reference):
    """Create a PayPal order for amount_str (e.g. '2.99'). Returns the order id."""
    tok = _token()
    r = httpx.post(
        _base() + "/v2/checkout/orders",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": reference,
                "amount": {"currency_code": currency, "value": amount_str},
                "description": "Token purchase",
            }],
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["id"]


def capture_order(order_id):
    """Capture an approved order. Returns (ok, amount_value, currency) — ok is True
    only when PayPal reports the capture COMPLETED."""
    tok = _token()
    r = httpx.post(
        _base() + f"/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "COMPLETED":
        return (False, None, None)
    cap = data["purchase_units"][0]["payments"]["captures"][0]
    amt = cap["amount"]
    return (cap.get("status") == "COMPLETED", amt.get("value"), amt.get("currency_code"))
