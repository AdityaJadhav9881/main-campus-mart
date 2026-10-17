import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ai import key_pool_engine

client = TestClient(app)


def test_ai_complete_hello_speed():
    start = time.monotonic()
    reply = key_pool_engine.ai_complete("hello", task_type="chat")
    duration = time.monotonic() - start

    assert isinstance(reply, str)
    assert len(reply) > 10
    # Strict speed requirement: must be responsive and fast
    assert duration < 5.0, f"ai_complete took {duration:.2f}s, exceeding budget"


def test_ai_complete_price_inquiry_speed():
    start = time.monotonic()
    reply = key_pool_engine.ai_complete(
        "what is a fair price for a calculator?", task_type="chat"
    )
    duration = time.monotonic() - start

    assert isinstance(reply, str)
    assert len(reply) > 10
    assert "₹" in reply or "INR" in reply or "price" in reply.lower()
    assert duration < 5.0, f"Price inquiry took {duration:.2f}s"


def test_ai_chat_endpoint_200_and_fast():
    from unittest.mock import MagicMock
    from app.auth import create_access_token
    from app.database import get_db
    from app.models import User
    from app.routers import chat

    mock_user = MagicMock(spec=User)
    mock_user.id = "test-speed-uid"
    mock_user.email = "student@campusmart.ai"
    mock_user.name = "Test Student"
    mock_user.college_name = "COEP Technological University"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.first.return_value = None

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[chat._current_user] = lambda: mock_user

    try:
        token = create_access_token(
            uid="test-speed-uid",
            email="student@campusmart.ai",
            name="Test Student",
        )
        start = time.monotonic()
        response = client.post(
            "/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "hello", "history": []},
        )
        duration = time.monotonic() - start

        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert len(data["reply"]) > 5
        assert "source" in data
        assert duration < 6.0, f"POST /ai/chat took {duration:.2f}s"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(chat._current_user, None)
