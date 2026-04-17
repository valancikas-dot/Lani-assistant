"""Payments routes – Stripe checkout sessions and webhook handler."""

from __future__ import annotations

import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.services import token_service

log = logging.getLogger(__name__)
router = APIRouter()

# ── Token packages ────────────────────────────────────────────────────────────
# id must be URL-safe and stable (used in Stripe metadata).

TOKEN_PACKAGES = [
    {
        "id": "starter",
        "name": "Starter",
        "price_eur": 10,
        "tokens": 10_000,
        "description": "Pradžiai",
        "highlight": False,
        "stripe_product_id": "prod_ULsC48JAFFU5Qm",
    },
    {
        "id": "standard",
        "name": "Standard",
        "price_eur": 20,
        "tokens": 22_000,
        "description": "+10% bonus tokenų",
        "highlight": False,
        "stripe_product_id": "prod_ULsGDw9xVPGk4k",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_eur": 40,
        "tokens": 50_000,
        "description": "+25% bonus tokenų",
        "highlight": True,
        "stripe_product_id": "prod_ULsHcXPdaKnxWS",
    },
    {
        "id": "max",
        "name": "Max",
        "price_eur": 100,
        "tokens": 140_000,
        "description": "+40% bonus tokenų",
        "highlight": False,
        "stripe_product_id": "prod_ULsHPFAKPfmJWY",
    },
]

_PKG_BY_ID: dict[str, dict] = {p["id"]: p for p in TOKEN_PACKAGES}


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenPackageOut(BaseModel):
    id: str
    name: str
    price_eur: int
    tokens: int
    description: str
    highlight: bool


class CheckoutRequest(BaseModel):
    package_id: str


class CheckoutResponse(BaseModel):
    checkout_url: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/payments/packages", response_model=list[TokenPackageOut])
async def list_packages() -> list[TokenPackageOut]:
    """Return all available token packages (public – no auth required)."""
    return [TokenPackageOut(**p) for p in TOKEN_PACKAGES]


@router.post("/payments/create-checkout", response_model=CheckoutResponse)
async def create_checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
) -> CheckoutResponse:
    """Create a Stripe Checkout session and return the redirect URL."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Mokėjimai šiuo metu neprieinami – Stripe raktas nenurodytas.",
        )

    pkg = _PKG_BY_ID.get(payload.package_id)
    if not pkg:
        raise HTTPException(status_code=400, detail="Nežinomas paketas")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        # If the package has an existing Stripe Product, reference it directly.
        # Otherwise describe the product inline (for packages not yet created in Stripe).
        stripe_product_id = pkg.get("stripe_product_id")
        if stripe_product_id:
            price_data: dict = {
                "currency": "eur",
                "unit_amount": pkg["price_eur"] * 100,
                "product": stripe_product_id,
            }
        else:
            price_data = {
                "currency": "eur",
                "unit_amount": pkg["price_eur"] * 100,
                "product_data": {
                    "name": f"Lani {pkg['name']} – {pkg['tokens']:,} tokenų",
                    "description": pkg["description"],
                },
            }

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{"price_data": price_data, "quantity": 1}],
            metadata={
                "user_id": str(user.id),
                "user_email": user.email,
                "package_id": pkg["id"],
                "tokens": str(pkg["tokens"]),
            },
            customer_email=user.email,
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
        )
    except stripe.StripeError as exc:
        log.error("Stripe checkout error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Stripe klaida: {exc.user_message}") from exc

    return CheckoutResponse(checkout_url=session.url)  # type: ignore[arg-type]


@router.post("/payments/webhook", status_code=200)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Stripe sends events here after payment. Adds tokens on checkout.session.completed."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    # Verify signature if webhook secret is configured
    if settings.STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except stripe.SignatureVerificationError as exc:
            log.warning("Stripe webhook signature failed: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid signature") from exc
    else:
        # Dev mode – skip verification
        import json
        event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        meta = session_obj.get("metadata", {})

        user_id = int(meta.get("user_id", 0))
        tokens = float(meta.get("tokens", 0))
        package_id = meta.get("package_id", "?")

        if user_id and tokens > 0:
            result = await db.execute(select(User).where(User.id == user_id))
            user: User | None = result.scalar_one_or_none()
            if user:
                new_balance = await token_service.top_up(
                    db,
                    user,
                    tokens,
                    description=f"Stripe pirkimas: {package_id} paketas",
                )
                log.info(
                    "Webhook: added %.0f tokens to user %s. New balance: %.0f",
                    tokens, user.email, new_balance,
                )
            else:
                log.warning("Webhook: user_id=%s not found", user_id)

    return {"status": "ok"}
