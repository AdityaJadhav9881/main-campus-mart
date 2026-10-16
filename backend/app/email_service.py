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

# Brand palette (inline-styled HTML - Brevo renders plain HTML only).
_BRAND = "#4f46e5"        # indigo - matches the marketplace accent
_BRAND_DARK = "#3730a3"
_SURFACE = "#f8fafc"
_TEXT = "#0f172a"
_MUTED = "#64748b"
_SUCCESS = "#16a34a"
_WARN = "#d97706"


def email_enabled() -> bool:
    """True when a Brevo API key is configured (tests clear it offline)."""
    return bool(BREVO_API_KEY)


def _inr(value: float | None) -> str:
    """Format an amount as Indian Rupees: 350.0 -> '₹350', 850.5 -> '₹850.50'."""
    if value is None:
        return "₹—"
    amount = float(value)
    if amount.is_integer():
        return f"₹{amount:,.0f}"
    return f"₹{amount:,.2f}"


# =============================================================================
# HTML shell shared by every template
# =============================================================================
def _shell(heading: str, body_html: str) -> str:
    """Wrap body markup in the Campus Mart Ai branded card layout."""
    return f"""<!DOCTYPE html>
<html>
  <body style="margin:0; padding:0; background:{_SURFACE};
               font-family:Segoe UI, Roboto, Helvetica, Arial, sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:{_SURFACE}; padding:24px 12px;">
      <tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="max-width:560px; width:100%; background:#ffffff;
                      border-radius:16px; overflow:hidden;
                      border:1px solid #e2e8f0;">
          <tr>
            <td style="background:linear-gradient(135deg, {_BRAND}, {_BRAND_DARK});
                       padding:22px 28px;">
              <div style="color:#ffffff; font-size:20px; font-weight:700;">
                Campus Mart Ai
              </div>
              <div style="color:#c7d2fe; font-size:12px; margin-top:4px;">
                Your campus second-hand marketplace
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:28px;">
              <h1 style="margin:0 0 16px 0; font-size:20px; color:{_TEXT};">
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
        f'<td style="padding:9px 0; border-bottom:1px solid #e2e8f0; '
        f'color:{_MUTED}; font-size:13px; width:44%;">{label}</td>'
        f'<td style="padding:9px 0; border-bottom:1px solid #e2e8f0; '
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
    """Product photo block (skipped when the listing has no photo)."""
    if not image_url:
        return ""
    return (
        f'<img src="{image_url}" alt="Listing photo" width="500"'
        f' style="display:block; width:100%; max-width:500px; border-radius:12px;'
        f' border:1px solid #e2e8f0; margin:18px 0;" />'
    )


# =============================================================================
# Transport
# =============================================================================
def _send_email(to_email: str | None, subject: str, html_content: str) -> bool:
    """POST one transactional email to Brevo. Never raises (log + False)."""
    if not to_email:
        logger.warning("email skipped (%s): no recipient address", subject)
        return False
    if not email_enabled():
        logger.info(
            "email skipped (BREVO_API_KEY not configured): to=%s subject=%s",
            to_email, subject,
        )
        return False

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                BREVO_API_URL,
                headers={
                    "api-key": BREVO_API_KEY,
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
      <div style="text-align:center; margin:22px 0;">
        <span style="display:inline-block; letter-spacing:10px;
                     font-size:34px; font-weight:800; color:{_BRAND};
                     background:{_BRAND}14; border:2px dashed {_BRAND};
                     border-radius:14px; padding:16px 18px 16px 28px;">
          {otp_code}
        </span>
      </div>
      <p style="margin:6px 0 0 0; color:{_WARN}; font-size:13px;
                font-weight:600; text-align:center;">
        Valid for 10 minutes only.
      </p>
      <p style="margin:16px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6; text-align:center;">
        Never share this code with anyone - Campus Mart Ai staff will
        never ask for it.
      </p>
    """
    return _send_email(to_email, subject, _shell("Verify your email", body))


# =============================================================================
# 2. Listing published confirmation
# =============================================================================
def send_listing_published_email(
    seller_email: str, seller_name: str, product
) -> bool:
    """Notify the seller that their listing went live (or is under review).

    `product` only needs scalar attributes (title, category, condition,
    listed_price, suggested_price, status, image_url) so a detached ORM row
    from a FastAPI BackgroundTask works fine.
    """
    subject = f"Your listing '{product.title}' is live on Campus Mart Ai!"

    moderation = product.status == "flagged"
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
        _row("Product", product.title)
        + _row("Category", product.category)
        + _row("Condition", product.condition)
        + _row("Listed Price", _inr(product.listed_price))
        + _row("AI Suggested Fair Price", _inr(product.suggested_price))
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
      {_image_html(product.image_url)}
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e2e8f0; border-radius:12px;
                    border-collapse:separate; overflow:hidden;">
        {rows}
      </table>
      <p style="margin:18px 0 0 0; color:{_MUTED}; font-size:12px;
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


def _send_sold_to_seller(seller, buyer, product, final_price: float) -> bool:
    subject = f"🎉 Sold! '{product.title}' was purchased on Campus Mart Ai"
    trust = getattr(seller, "trust_score", None)
    rows = (
        _row("Item Sold", product.title)
        + _row("Condition", product.condition)
        + _row("Sale Price", _inr(final_price))
        + _row("Buyer", buyer.name)
        + _row("Buyer Email", buyer.email)
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
        Congrats {seller.name} - it's sold! 🎉
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        A student just bought your listing. Meet up on campus to hand over
        the item, and your trust score just went up for the smooth sale.
      </p>
      {_image_html(product.image_url)}
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e2e8f0; border-radius:12px;
                    border-collapse:separate; overflow:hidden;">
        {rows}
      </table>
      <p style="margin:18px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6;">
        Your listing has been marked <b>Sold</b> and removed from the
        Discover feed automatically.
      </p>
    """
    return _send_email(seller.email, subject, _shell("Item sold", body))


def _send_order_to_buyer(seller, buyer, product, final_price: float) -> bool:
    subject = f"Order Confirmed: '{product.title}' on Campus Mart Ai"
    rows = (
        _row("Item", product.title)
        + _row("Category", product.category)
        + _row("Condition", product.condition)
        + _row("Price Paid", _inr(final_price))
        + _row("Seller", seller.name)
        + _row("Seller Email", seller.email)
    )
    body = f"""
      <p style="margin:0 0 14px 0; color:{_TEXT}; font-size:14px;">
        Thanks {buyer.name} - your order is confirmed!
      </p>
      <p style="margin:0 0 10px 0; color:{_MUTED}; font-size:14px;
                line-height:1.6;">
        You bought this item on Campus Mart Ai. Arrange the campus pickup
        with your seller using the in-app Messages tab.
      </p>
      {_image_html(product.image_url)}
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e2e8f0; border-radius:12px;
                    border-collapse:separate; overflow:hidden;">
        {rows}
      </table>
      <p style="margin:18px 0 0 0; color:{_MUTED}; font-size:12px;
                line-height:1.6;">
        Meet in a public campus spot and inspect the item before handing
        over the payment. Happy trading!
      </p>
    """
    return _send_email(buyer.email, subject, _shell("Order confirmed", body))
