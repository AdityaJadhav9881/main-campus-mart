import pytest
from app.schemas import CheckoutRequest
from app.email_service import (
    send_otp_email,
    send_listing_published_email,
    send_product_sold_emails,
    _shell,
    _image_html,
)


def test_checkout_request_payment_method_normalization():
    # Test 'Cash on Meetup' variant
    req1 = CheckoutRequest(
        payment_method="Cash on Meetup",
        delivery_address="Hostel 4, Room 201",
        contact_phone="9876543210",
    )
    assert req1.payment_method == "cash_on_meetup"

    # Test 'gpay' variant
    req2 = CheckoutRequest(
        payment_method="GPay / UPI",
        delivery_address="Library Ground Floor",
        contact_phone="9876543210",
    )
    assert req2.payment_method == "gpay_upi"

    # Test None / default
    req3 = CheckoutRequest(
        payment_method=None,
        delivery_address="Main Gate",
        contact_phone="9876543210",
    )
    assert req3.payment_method == "cash_on_meetup"

    # Test standard exact matches
    req4 = CheckoutRequest(payment_method="cash_on_meetup")
    assert req4.payment_method == "cash_on_meetup"

    req5 = CheckoutRequest(payment_method="gpay_upi")
    assert req5.payment_method == "gpay_upi"


def test_email_shell_and_image_formatting():
    shell_html = _shell("Test Heading", "<p>Hello Student</p>")
    assert 'meta name="color-scheme" content="light"' in shell_html
    assert 'meta name="supported-color-schemes" content="light"' in shell_html
    assert "Test Heading" in shell_html
    assert "Hello Student" in shell_html

    img_html = _image_html("https://example.com/item.jpg")
    assert 'width="110" height="110"' in img_html
    assert "object-fit:cover" in img_html
    assert "border-radius:14px" in img_html


def test_email_templates_render_without_raising():
    product_mock = {
        "title": "Casio FX-991EX Classwiz",
        "category": "Electronics",
        "condition": "Like New",
        "listed_price": 750.0,
        "suggested_price": 700.0,
        "image_url": "https://example.com/calc.jpg",
        "status": "active",
    }
    seller_mock = {
        "name": "Aarav Sharma",
        "email": "aarav@campus.edu",
        "trust_score": 4.8,
    }
    buyer_mock = {
        "name": "Priya Patel",
        "email": "priya@campus.edu",
    }

    # Should safely return boolean (in test environment BREVO_API_KEY is empty so it returns False cleanly without crashing)
    assert send_otp_email("test@campus.edu", "Student", "123456") is False
    assert (
        send_listing_published_email(
            "test@campus.edu", "Aarav", product_mock
        )
        is False
    )
    assert (
        send_product_sold_emails(
            seller_mock, buyer_mock, product_mock, 750.0
        )
        is False
    )
