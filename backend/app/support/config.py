"""Which provider sells the supporter pass, from the environment (#1473).

`SUPPORT_PROVIDER` unset turns the whole tier off: no button, no routes, no
status field, so a self-hosted deployment that sells nothing shows nothing.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain_values import SupportProvider

# A `stub` deployment is development or the end-to-end suite, and needs no
# setup. Production refuses `stub` outright (`validate_support_configuration`).
STUB_WEBHOOK_SECRET = "stub-webhook-secret"
PADDLE_API_URL = "https://api.paddle.com"
# The most a single "add a one-time extra" may add, in minor units. An extra is
# a gift of goodwill, and a typo should not be able to become a large charge.
MAX_EXTRA_MINOR = 50_000


@dataclass(frozen=True)
class SupportConfig:
    provider: str
    webhook_secret: str
    api_key: str = ""
    api_url: str = PADDLE_API_URL
    price_year: str = ""
    price_lifetime: str = ""
    # Twelve months, one charge, never renewing (#1540).
    price_gift: str = ""
    # The product a non-catalog "extra" line is sold under.
    extra_product_id: str = ""
    # The page Paddle's payment link opens on. Paddle requires Paddle.js there,
    # and R-PLAT-20 forbids it on this origin, so it lives elsewhere: see
    # `ops/paddle-checkout/`. Unset uses the account's default payment link.
    checkout_url: str = ""
    # What the pitch shows. Paddle's checkout shows the buyer's real total.
    year_label: str = "€19"
    lifetime_label: str = "€69"
    gift_label: str = "€19"
    # An outbound link for a tip with nothing in return. Not a provider: no
    # script, no webhook, no data, and it never counts toward a pass.
    tip_url: str = ""


def support_config(environ: Mapping[str, str] | None = None) -> SupportConfig | None:
    """The tier's configuration, or None when the deployment sells nothing."""
    values = os.environ if environ is None else environ
    provider = values.get("SUPPORT_PROVIDER", "").strip().lower()
    if not provider:
        return None
    secret = values.get("SUPPORT_WEBHOOK_SECRET", "").strip()
    if provider == SupportProvider.STUB.value:
        secret = secret or STUB_WEBHOOK_SECRET
    return SupportConfig(
        provider=provider,
        webhook_secret=secret,
        api_key=values.get("SUPPORT_API_KEY", "").strip(),
        api_url=values.get("SUPPORT_API_URL", "").strip().rstrip("/") or PADDLE_API_URL,
        price_year=values.get("SUPPORT_PRICE_YEAR", "").strip(),
        price_lifetime=values.get("SUPPORT_PRICE_LIFETIME", "").strip(),
        price_gift=values.get("SUPPORT_PRICE_GIFT", "").strip(),
        extra_product_id=values.get("SUPPORT_EXTRA_PRODUCT_ID", "").strip(),
        checkout_url=values.get("SUPPORT_CHECKOUT_URL", "").strip(),
        year_label=values.get("SUPPORT_YEAR_LABEL", "").strip() or "€19",
        lifetime_label=values.get("SUPPORT_LIFETIME_LABEL", "").strip() or "€69",
        gift_label=values.get("SUPPORT_GIFT_LABEL", "").strip() or "€19",
        tip_url=values.get("SUPPORT_TIP_URL", "").strip(),
    )
