import os
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import add_message, check_db_health, get_db, init_db
from app.main import app


@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path, monkeypatch) -> Generator[str, None, None]:
    """
    Ensure every test runs against an isolated, temporary SQLite database.
    Never modifies the development or production database file.
    """
    test_db_path = str(tmp_path / "test_app.db")
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{test_db_path}")

    # Initialize tables and indexes on the test database
    import asyncio
    asyncio.run(init_db(test_db_path))

    yield test_db_path


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client


def test_database_initialization(isolated_test_db: str):
    """Test 1: Verify tables and indexes are created automatically on database initialization."""
    import asyncio

    async def verify_tables():
        assert await check_db_health(isolated_test_db) is True
        async with get_db(isolated_test_db) as db:
            # Check messages table
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
            )
            table = await cursor.fetchone()
            assert table is not None
            assert table[0] == "messages"

            # Check index on session_id
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_session_id';"
            )
            index = await cursor.fetchone()
            assert index is not None
            assert index[0] == "idx_messages_session_id"

    asyncio.run(verify_tables())


def test_health_endpoint_unhealthy_when_no_keys(client: TestClient, monkeypatch):
    """Test 2: GET /health returns 503 when fewer than 2 API keys are configured."""
    monkeypatch.setattr(settings, "LLM_API_KEYS", "")
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["keys_configured"] == 0
    assert data["cache_enabled"] is False
    assert "detail" in data


def test_health_endpoint_healthy_with_keys(client: TestClient, monkeypatch):
    """Test 3: GET /health returns 200 when DB is reachable and key pool has >= 2 keys."""
    monkeypatch.setattr(settings, "LLM_API_KEYS", "key_1,key_2")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": True,
    }


def test_post_chat_rejects_empty_message(client: TestClient):
    """Test 4: POST /chat rejects empty string or whitespace-only messages with 422."""
    # Empty string
    res1 = client.post("/chat", json={"session_id": "s-100", "message": ""})
    assert res1.status_code == 422
    assert "detail" in res1.json()

    # Whitespace only
    res2 = client.post("/chat", json={"session_id": "s-100", "message": "   \n\t  "})
    assert res2.status_code == 422
    assert "detail" in res2.json()


def test_post_chat_rejects_message_over_4000_chars(client: TestClient):
    """Test 5: POST /chat rejects messages over 4000 characters after whitespace trimming."""
    long_msg = "a" * 4001
    response = client.post("/chat", json={"session_id": "s-100", "message": long_msg})
    assert response.status_code == 422
    assert "detail" in response.json()

    # Exactly 4000 chars is valid schema (though returns 503 until LLM service is integrated)
    valid_long = "a" * 4000
    res_valid = client.post("/chat", json={"session_id": "s-100", "message": valid_long})
    assert res_valid.status_code == 503


def test_post_chat_rejects_missing_or_invalid_session_id(client: TestClient):
    """Test 6: POST /chat rejects missing, empty, or > 128 char session_id."""
    # Missing session_id
    res1 = client.post("/chat", json={"message": "Valid message"})
    assert res1.status_code == 422

    # Empty session_id
    res2 = client.post("/chat", json={"session_id": "", "message": "Valid message"})
    assert res2.status_code == 422

    # Over 128 characters
    res3 = client.post(
        "/chat", json={"session_id": "s" * 129, "message": "Valid message"}
    )
    assert res3.status_code == 422


def test_post_chat_service_boundary_returns_503(client: TestClient):
    """
    Test 7: In Step 2, POST /chat cleanly returns 503 {"detail": "all providers unavailable"}
    until LiteLLM service integration is added in Step 3.
    """
    response = client.post(
        "/chat",
        json={"session_id": "s-boundary-test", "message": "Hello world!"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}


def test_x_simulate_failure_header_accepted(client: TestClient):
    """Test 8: X-Simulate-Failure header is parsed and accepted by POST /chat."""
    response = client.post(
        "/chat",
        json={"session_id": "s-header-test", "message": "Testing header"},
        headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}


def test_unknown_session_returns_404(client: TestClient):
    """Test 9: GET /sessions/{session_id}/messages returns 404 for unknown sessions."""
    response = client.get("/sessions/s-nonexistent-9999/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_session_history_retrieval_order_and_metadata(
    client: TestClient, isolated_test_db: str
):
    """
    Test 10: GET /sessions/{session_id}/messages returns messages oldest first,
    parses assistant metadata as JSON, omits user metadata, and excludes system prompt.
    """
    import asyncio

    session_id = "s-7f3a"

    # Pre-populate session messages in SQLite
    async def populate():
        await add_message(
            session_id=session_id,
            role="user",
            content="What is the capital of France?",
            metadata=None,
            db_path=isolated_test_db,
        )
        await add_message(
            session_id=session_id,
            role="assistant",
            content="The capital of France is Paris.",
            metadata={
                "resolution_source": "LIVE_INFERENCE",
                "input_tokens": 42,
                "output_tokens": 9,
            },
            db_path=isolated_test_db,
        )
        await add_message(
            session_id=session_id,
            role="user",
            content="What is its population?",
            metadata=None,
            db_path=isolated_test_db,
        )
        await add_message(
            session_id=session_id,
            role="assistant",
            content="Around 2.1 million.",
            metadata={
                "resolution_source": "LLM_CACHE",
                "input_tokens": 60,
                "output_tokens": 12,
            },
            db_path=isolated_test_db,
        )

    asyncio.run(populate())

    response = client.get(f"/sessions/{session_id}/messages")
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] == session_id
    messages = data["messages"]
    assert len(messages) == 4

    # 1st message (user)
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the capital of France?"
    assert "metadata" not in messages[0] or messages[0]["metadata"] is None

    # 2nd message (assistant)
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "The capital of France is Paris."
    assert messages[1]["metadata"] == {
        "resolution_source": "LIVE_INFERENCE",
        "input_tokens": 42,
        "output_tokens": 9,
    }

    # 3rd message (user)
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "What is its population?"

    # 4th message (assistant)
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == "Around 2.1 million."
    assert messages[3]["metadata"] == {
        "resolution_source": "LLM_CACHE",
        "input_tokens": 60,
        "output_tokens": 12,
    }


def test_no_history_mutation_on_failed_chat_requests(
    client: TestClient, isolated_test_db: str
):
    """
    Test 11: A request that fails (422 or 503) is never added to the session history.
    """
    failed_session = "s-fail-test"

    # Attempt failed chat request (503)
    res_503 = client.post(
        "/chat",
        json={"session_id": failed_session, "message": "Failed message attempt"},
    )
    assert res_503.status_code == 503

    # Attempt malformed chat request (422)
    res_422 = client.post(
        "/chat",
        json={"session_id": failed_session, "message": ""},
    )
    assert res_422.status_code == 422

    # Querying history must return 404 because no messages were stored
    res_history = client.get(f"/sessions/{failed_session}/messages")
    assert res_history.status_code == 404
    assert res_history.json() == {"detail": "session not found"}
