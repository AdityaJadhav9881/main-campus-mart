"""
email_service.py
================
Transactional email engine for Campus Mart Ai (Brevo SMTP API).

Three branded HTML emails ship from the verified sender mailbox:

    send_otp_email()                - 6-digit registration verification code
                                      (POST /auth/send-otp + /auth/resend-otp)
    send_listing_published_email()  - "your listing is live" confirmation
                                      (queued by POST /products/)
    send_product_sold_emails()      - sold notice to the seller + order
                                      confirmation to the buyer (queued by
                                      POST /products/{id}/purchase)

Transport
---------
Brevo's HTTPS API:  POST https://api.brevo.com/v3/smtp/email
Header:             api-key: <BREVO_API_KEY>
Sender:             {"name": "Campus Mart Ai", "email": "martaicampus@gmail.com"}

SAFETY RULE (non-blocking by design)
------------------------------------
Every public function is wrapped so a network hiccup, missing key or Brevo
outage logs a warning and returns - it NEVER raises. A failed email must not
break listing creation, checkout, OTP signup, or any offline pytest run
(conftest.py clears BREVO_API_KEY so tests never hit the real API).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from typing import Any

logger = logging.getLogger(__name__)

# Resolve /backend/.env regardless of the process working directory.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL: str = (
    os.getenv("BREVO_SENDER_EMAIL", "martaicampus@gmail.com").strip()
    or "martaicampus@gmail.com"
)
BREVO_SENDER_NAME: str = (
    os.getenv("BREVO_SENDER_NAME", "Campus Mart Ai").strip() or "Campus Mart Ai"
)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
# Short budget: emails run as FastAPI BackgroundTasks - never hold a response.
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def get_brevo_config(db=None) -> tuple[str, str, str]:
    """Resolve (api_key, sender_email, sender_name) with fallback to SystemConfig."""
    global BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME
    api_key = BREVO_API_KEY
    sender_email = BREVO_SENDER_EMAIL or "martaicampus@gmail.com"
    sender_name = BREVO_SENDER_NAME or "Campus Mart Ai"

    if not api_key:
        try:
            from .database import SessionLocal
            from .models import SystemConfig

            local_session = False
            session = db
            if session is None:
                session = SessionLocal()
                local_session = True
            try:
                row = (
                    session.query(SystemConfig)
                    .filter(SystemConfig.key == "brevo_api_key")
                    .first()
                )
                if row and row.value:
                    api_key = row.value.strip()
                row_email = (
                    session.query(SystemConfig)
                    .filter(SystemConfig.key == "brevo_sender_email")
                    .first()
                )
                if row_email and row_email.value:
                    sender_email = row_email.value.strip()
                row_name = (
                    session.query(SystemConfig)
                    .filter(SystemConfig.key == "brevo_sender_name")
                    .first()
                )
                if row_name and row_name.value:
                    sender_name = row_name.value.strip()
            finally:
                if local_session:
                    session.close()
        except Exception as err:
            logger.debug("SystemConfig lookup for Brevo credentials: %s", err)

    return api_key, sender_email, sender_name


def email_enabled() -> bool:
    """True when a Brevo API key is configured (tests clear it offline)."""
    api_key, _, _ = get_brevo_config()
    return bool(api_key)


def _inr(value: float | None) -> str:
    """Format an amount as Indian Rupees: 350.0 -> '₹350', 850.5 -> '₹850.50'."""
    if value is None:
        return "₹—"
    amount = float(value)
    if amount.is_integer():
        return f"₹{amount:,.0f}"
    return f"₹{amount:,.2f}"


# Design tokens matching Campus Mart Ai Warm Paper theme
_BRAND = "#2563eb"       # Royal Blue
_BRAND_DARK = "#1d4ed8"  # Darker Royal Blue for gradient
_SURFACE = "#faf9f6"     # Warm Paper Cream
_TEXT = "#141413"        # Ink Black
_MUTED = "#6b7280"       # Muted Gray
_WARN = "#d97706"        # Amber
_SUCCESS = "#15803d"     # Matte Forest Green
_DANGER = "#dc2626"      # Danger Red


# =============================================================================
# HTML shell shared by every template
# =============================================================================
def _shell(heading: str, body_html: str) -> str:
    """Wrap body markup in the Campus Mart Ai branded card layout."""
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <style>
      :root {{
        color-scheme: light;
        supported-color-schemes: light;
      }}
      body {{
        margin: 0;
        padding: 0;
        background: {_SURFACE};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      }}
    </style>
  </head>
  <body style="margin:0; padding:0; background:{_SURFACE};
               font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
               -webkit-font-smoothing:antialiased;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:{_SURFACE}; padding:24px 12px;">
      <tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="max-width:560px; width:100%; background:#ffffff;
                      border-radius:16px; overflow:hidden;
                      border:1px solid #e2e8f0; box-shadow:0 4px 14px rgba(0,0,0,0.04);">
          <tr>
            <td style="background:linear-gradient(135deg, {_BRAND}, {_BRAND_DARK});
                       padding:22px 28px;">
              <div style="color:#ffffff; font-size:20px; font-weight:700; letter-spacing:-0.2px;">
                Campus Mart Ai
              </div>
              <div style="color:#c7d2fe; font-size:12px; margin-top:4px;">
                Your campus second-hand marketplace
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:28px;">
              <h1 style="margin:0 0 16px 0; font-size:20px; font-weight:700; color:{_TEXT};">
                {heading}
              </h1>
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="padding:18px 28px; background:{_SURFACE};
                       border-top:1px solid #e2e8f0;">
              <div style="font-size:12px; color:{_MUTED}; line-height:1.6;">
                Sent by Campus Mart Ai &middot; trusted student-to-student
                trading on campus.<br/>
                Questions or need help? Reply to this email or contact us at <a href="mailto:martaicampus@gmail.com" style="color:{_BRAND}; text-decoration:none; font-weight:600;">martaicampus@gmail.com</a>.<br/>
                If you didn't request this email, you can safely ignore it.
              </div>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""


def _row(label: str, value: str) -> str:
    """One label/value row used by the listing + order templates."""
    return (
        f'<tr>'
        f'<td style="padding:10px 0; border-bottom:1px solid #e5e7eb; '
        f'color:{_MUTED}; font-size:13px; text-align:left;">{label}</td>'
        f'<td style="padding:10px 0; border-bottom:1px solid #e5e7eb; '
        f'color:{_TEXT}; font-size:13px; font-weight:600; text-align:right;">'
        f"{value}</td>"
        f"</tr>"
    )


def _pill(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block; padding:4px 12px; border-radius:999px; '
        f'background:{color}22; color:{color}; font-size:12px; font-weight:700;">'
        f"{text}</span>"
    )


def _image_html(image_url: str | None) -> str:
    """Product photo block - fixed 110x110 square thumbnail with object-fit: cover."""
    if not image_url:
        return ""
    return (
        f'<div style="text-align:center; margin:0 auto 14px auto;">'
        f'<img src="{image_url}" alt="Listing photo" width="110" height="110"'
        f' style="display:inline-block; width:110px; height:110px; max-width:110px; max-height:110px;'
        f' object-fit:cover; border-radius:14px; border:1px solid #e5e7eb;'
        f' box-shadow:0 2px 8px rgba(0,0,0,0.06);" />'
        f'</div>'
    )


# =============================================================================
# Transport
# =============================================================================
def _send_email(to_email: str | None, subject: str, html_content: str) -> bool:
    """POST one transactional email to Brevo. Never raises (log + False)."""
    if not to_email:
        logger.warning("email skipped (%s): no recipient address", subject)
        return False

    api_key, sender_email, sender_name = get_brevo_config()
    if not api_key:
        logger.info(
            "email skipped (BREVO_API_KEY not configured): to=%s subject=%s",
            to_email, subject,
        )
        return False

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                BREVO_API_URL,
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        logger.info("email sent to=%s subject=%r", to_email, subject)
        return True
    except Exception as exc:  # noqa: BLE001 - email must never break the API
        logger.warning(
            "Brevo email FAILED (non-blocking) to=%s subject=%r: %s",
            to_email, subject, exc,
        )
        return False


# =============================================================================
# 1. Registration OTP (6-digit code)
# =============================================================================
def send_otp_email(to_email: str, name: str, otp_code: str) -> bool:
    """Send the 6-digit signup verification code (valid 10 minutes)."""
    subject = f"Your Campus Mart Ai Verification Code: {otp_code}"
    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Hi {name},
      </p>
      <p style="margin:0 0 18px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        Use this code to verify your email and finish creating your
        Campus Mart Ai account:
      </p>
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:16px;
                  padding:24px 16px; margin:20px 0; text-align:center;">
        <div style="letter-spacing:10px; font-size:36px; font-weight:800;
                    color:{_BRAND}; line-height:1.2;">
          {otp_code}
        </div>
        <p style="margin:10px 0 0 0; color:{_WARN}; font-size:13px; font-weight:600;">
          Valid for 10 minutes only
        </p>
      </div>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6; text-align:center;">
        Never share this code with anyone - Campus Mart Ai staff will
        never ask for it.
      </p>
    """
    return _send_email(to_email, subject, _shell("Verify your email", body))


# =============================================================================
# 1b. Action OTP (verify before publish / purchase)
# =============================================================================
def send_action_otp_email(
    to_email: str,
    name: str,
    otp_code: str,
    action_type: str = "purchase",
    item_title: str | None = None,
) -> bool:
    """Send the 6-digit code that authorises a sensitive action.

    action_type: 'sell'     -> publishing a listing
                 'purchase' -> placing an order
    item_title : optional headline shown in the email ("Bose QC35 II").
    """
    action_label = "Sell" if action_type == "sell" else "Purchase"
    action_phrase = (
        "publish your listing"
        if action_type == "sell"
        else "place your order"
    )
    item_line = (
        f'<div style="font-size:15px; font-weight:700; color:{_TEXT}; '
        f'margin:0 0 12px 0;">Item: {item_title}</div>'
        if item_title
        else ""
    )
    subject = f"Your Campus Mart AI {action_label} Verification Code: {otp_code}"
    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Hi {name},
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        Use this code to confirm your identity and {action_phrase} on
        Campus Mart Ai:
      </p>
      {item_line}
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:16px;
                  padding:24px 16px; margin:20px 0; text-align:center;">
        <div style="letter-spacing:10px; font-size:36px; font-weight:800;
                    color:{_BRAND}; line-height:1.2;">
          {otp_code}
        </div>
        <p style="margin:10px 0 0 0; color:{_WARN}; font-size:13px; font-weight:600;">
          Valid for 10 minutes only
        </p>
      </div>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6; text-align:center;">
        Never share this code with anyone - Campus Mart Ai staff will
        never ask for it.
      </p>
    """
    heading = (
        "Confirm: publish your listing"
        if action_type == "sell"
        else "Confirm: place your order"
    )
    return _send_email(to_email, subject, _shell(heading, body))


# =============================================================================
# 2. Listing published confirmation
# =============================================================================
def send_listing_published_email(
    seller_email: str, seller_name: str, product
) -> bool:
    """Notify the seller that their listing went live (or is under review).

    `product` can be a detached ORM row or a snapshot dict.
    """
    def _get(key, default=None):
        if isinstance(product, dict):
            return product.get(key, default)
        return getattr(product, key, default)

    title = _get("title", "Item")
    status = _get("status", "active")
    category = _get("category", "General")
    condition = _get("condition", "Good")
    listed_price = _get("listed_price", 0.0)
    suggested_price = _get("suggested_price")
    image_url = _get("image_url")

    subject = f"Your listing '{title}' is live on Campus Mart Ai!"

    moderation = status == "flagged"
    status_pill = (
        _pill("Under Moderation Review", _WARN)
        if moderation
        else _pill("Active", _SUCCESS)
    )
    status_note = (
        "Our Trust &amp; Fraud agent is reviewing this listing - it will "
        "appear in the marketplace feed as soon as moderation approves it."
        if moderation
        else "Your listing is visible in the Discover feed right now."
    )

    rows = (
        _row("Category", category)
        + _row("Condition", condition)
        + (
            _row("AI Suggested Fair Price", _inr(suggested_price))
            if suggested_price
            else ""
        )
        + _row("Trust &amp; Safety Status", status_pill)
    )

    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Namaste {seller_name},
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        {status_note}
      </p>
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:16px;
                  padding:22px 18px; margin:18px 0; text-align:center;">
        {_image_html(image_url)}
        <div style="font-size:18px; font-weight:700; color:{_TEXT}; margin:0 0 6px 0; line-height:1.4;">
          {title}
        </div>
        <div style="font-size:22px; font-weight:800; color:#10b981; margin:0 0 16px 0;">
          {_inr(listed_price)}
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb; margin-top:8px;">
          {rows}
        </table>
      </div>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6;">
        Tip: keep an eye on your Messages tab - buyers can message you
        directly from the listing.
      </p>
    """
    heading = "Your listing is live!"
    return _send_email(seller_email, subject, _shell(heading, body))


# =============================================================================
# 3. Product sold (seller notice + buyer confirmation)
# =============================================================================
def send_product_sold_emails(
    seller, buyer, product, final_price: float
) -> bool:
    """Send BOTH sale emails (seller first, buyer second).

    `seller`/`buyer` need scalar .name/.email (detached ORM rows are fine);
    `product` needs .title/.category/.condition/.image_url/.listed_price.
    """
    sent_seller = _send_sold_to_seller(seller, buyer, product, final_price)
    sent_buyer = _send_order_to_buyer(seller, buyer, product, final_price)
    return sent_seller and sent_buyer


def _val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _send_sold_to_seller(seller, buyer, product, final_price: float) -> bool:
    title = _val(product, "title", "Item")
    condition = _val(product, "condition", "Good")
    image_url = _val(product, "image_url")
    seller_name = _val(seller, "name", "Seller")
    seller_email = _val(seller, "email")
    buyer_name = _val(buyer, "name", "Buyer")
    buyer_email = _val(buyer, "email")
    trust = _val(seller, "trust_score", 5.0)

    subject = f"🎉 Sold! '{title}' was purchased on Campus Mart Ai"
    rows = (
        _row("Condition", condition)
        + _row("Buyer", buyer_name)
        + _row("Buyer Email", buyer_email or "Not provided")
        + _row(
            "Your Trust Score",
            _pill(
                f"{float(trust):.1f}/5.0 (+0.1 this sale)",
                _SUCCESS,
            ),
        )
    )
    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Congrats {seller_name} - it's sold! 🎉
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        A student just bought your listing. Meet up on campus to hand over
        the item, and your trust score just went up for the smooth sale.
      </p>
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:16px;
                  padding:22px 18px; margin:18px 0; text-align:center;">
        {_image_html(image_url)}
        <div style="font-size:18px; font-weight:700; color:{_TEXT}; margin:0 0 6px 0; line-height:1.4;">
          {title}
        </div>
        <div style="font-size:22px; font-weight:800; color:#10b981; margin:0 0 16px 0;">
          {_inr(final_price)}
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb; margin-top:8px;">
          {rows}
        </table>
      </div>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6;">
        Your listing has been marked <b>Sold</b> and removed from the
        Discover feed automatically.
      </p>
    """
    return _send_email(seller_email, subject, _shell("Item sold", body))


def _send_order_to_buyer(seller, buyer, product, final_price: float) -> bool:
    title = _val(product, "title", "Item")
    category = _val(product, "category", "General")
    condition = _val(product, "condition", "Good")
    image_url = _val(product, "image_url")
    seller_name = _val(seller, "name", "Seller")
    seller_email = _val(seller, "email")
    buyer_name = _val(buyer, "name", "Buyer")
    buyer_email = _val(buyer, "email")

    subject = f"Order Confirmed: '{title}' on Campus Mart Ai"
    rows = (
        _row("Category", category)
        + _row("Condition", condition)
        + _row("Seller", seller_name)
        + _row("Seller Email", seller_email or "Not provided")
    )
    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Thanks {buyer_name} - your order is confirmed!
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        You bought this item on Campus Mart Ai. Arrange the campus pickup
        with your seller using the in-app Messages tab.
      </p>
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:16px;
                  padding:22px 18px; margin:18px 0; text-align:center;">
        {_image_html(image_url)}
        <div style="font-size:18px; font-weight:700; color:{_TEXT}; margin:0 0 6px 0; line-height:1.4;">
          {title}
        </div>
        <div style="font-size:22px; font-weight:800; color:#10b981; margin:0 0 16px 0;">
          {_inr(final_price)}
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb; margin-top:8px;">
          {rows}
        </table>
      </div>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6;">
        Meet in a public campus spot and inspect the item before handing
        over the payment. Happy trading!
      </p>
    """
    return _send_email(buyer_email, subject, _shell("Order confirmed", body))
