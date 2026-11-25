import asyncio
from typing import Generator
from unittest.mock import MagicMock, patch
import httpx
import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import add_message, check_db_health, get_db, init_db
from app.llm_service import init_llm_cache
from app.main import app


def make_gemini_http_response(
    text: str = "Paris is the capital of France.",
    prompt_tokens: int = 42,
    completion_tokens: int = 9,
    status_code: int = 200,
) -> httpx.Response:
    """Create a realistic Gemini REST API httpx.Response for mocking LiteLLM's HTTP layer."""
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent")
    if status_code != 200:
        return httpx.Response(
            status_code=status_code,
            json={"error": {"code": status_code, "message": f"Simulated HTTP {status_code}"}},
            request=req,
        )
    return httpx.Response(
        status_code=200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": completion_tokens,
                "totalTokenCount": prompt_tokens + completion_tokens,
            },
        },
        request=req,
    )


@pytest.fixture(autouse=True)
def isolated_test_env(tmp_path, monkeypatch) -> Generator[str, None, None]:
    """
    Ensure every test runs against:
    - An isolated, temporary SQLite database
    - A fresh in-memory LiteLLM cache
    - Mock API keys (never real credentials)
    """
    test_db_path = str(tmp_path / "test_app.db")
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setattr(settings, "LLM_API_KEYS", "mock_key_1,mock_key_2")
    monkeypatch.setattr(settings, "ENABLE_FAILURE_SIMULATION", False)

    asyncio.run(init_db(test_db_path))
    init_llm_cache()

    yield test_db_path


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client


def test_database_initialization(isolated_test_env: str):
    """Verify tables and session_id index are created automatically on startup."""
    async def verify_tables():
        assert await check_db_health(isolated_test_env) is True
        async with get_db(isolated_test_env) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages';"
            )
            table = await cursor.fetchone()
            assert table is not None and table[0] == "messages"

            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_session_id';"
            )
            index = await cursor.fetchone()
            assert index is not None and index[0] == "idx_messages_session_id"

    asyncio.run(verify_tables())


def test_health_endpoint_unhealthy_when_no_keys(client: TestClient, monkeypatch):
    """GET /health returns 503 when fewer than 2 API keys are configured."""
    monkeypatch.setattr(settings, "LLM_API_KEYS", "")
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["keys_configured"] == 0
    assert "detail" in data


def test_health_endpoint_reports_cache_status(client: TestClient, monkeypatch):
    """GET /health returns cache_enabled=true only when LiteLLM cache is initialized."""
    monkeypatch.setattr(settings, "LLM_API_KEYS", "key_1,key_2")

    # Cache initialized (via lifespan)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": True,
    }

    # Cache uninitialized
    monkeypatch.setattr(litellm, "cache", None)
    response_no_cache = client.get("/health")
    assert response_no_cache.status_code == 200
    assert response_no_cache.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": False,
    }


def test_post_chat_request_validation(client: TestClient):
    """POST /chat enforces session_id and message validation rules (422)."""
    # Empty / whitespace message
    assert client.post("/chat", json={"session_id": "s-100", "message": ""}).status_code == 422
    assert client.post("/chat", json={"session_id": "s-100", "message": "  \n\t "}).status_code == 422

    # Over 4000 chars
    assert client.post("/chat", json={"session_id": "s-100", "message": "a" * 4001}).status_code == 422

    # Missing, empty, or >128 char session_id
    assert client.post("/chat", json={"message": "Valid"}).status_code == 422
    assert client.post("/chat", json={"session_id": "", "message": "Valid"}).status_code == 422
    assert client.post("/chat", json={"session_id": "s" * 129, "message": "Valid"}).status_code == 422


@patch("app.llm_service.acompletion")
def test_first_key_success(mock_acompletion, client: TestClient):
    """First-key success records key_1, fallback_attempts=0, and LIVE_INFERENCE."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Paris is the capital of France."))]
    mock_resp.model = settings.LLM_MODEL
    mock_resp.usage = MagicMock(prompt_tokens=42, completion_tokens=9)
    mock_resp._hidden_params = {}
    mock_acompletion.return_value = mock_resp

    response = client.post(
        "/chat",
        json={"session_id": "s-key1-ok", "message": "What is the capital of France?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Paris is the capital of France."
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data["metadata"]["key_id"] == "key_1"
    assert data["metadata"]["fallback_attempts"] == 0
    assert data["metadata"]["input_tokens"] == 42
    assert data["metadata"]["output_tokens"] == 9
    assert isinstance(data["metadata"]["latency_ms"], int)
    assert mock_acompletion.call_args.kwargs["api_key"] == "mock_key_1"


@patch("app.llm_service.acompletion")
def test_key1_429_failover_to_key2_success(mock_acompletion, client: TestClient):
    """When key_1 returns 429 RateLimitError, falls over to key_2 with fallback_attempts=1."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Recovered on key_2"))]
    mock_resp.model = settings.LLM_MODEL
    mock_resp.usage = MagicMock(prompt_tokens=20, completion_tokens=5)
    mock_resp._hidden_params = {}

    rate_limit_exc = litellm.RateLimitError(
        message="429 quota exceeded", llm_provider="gemini", model=settings.LLM_MODEL
    )
    mock_acompletion.side_effect = [rate_limit_exc, mock_resp]

    response = client.post(
        "/chat",
        json={"session_id": "s-429-failover", "message": "Test 429 failover"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Recovered on key_2"
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert mock_acompletion.call_count == 2
    assert mock_acompletion.call_args_list[0].kwargs["api_key"] == "mock_key_1"
    assert mock_acompletion.call_args_list[1].kwargs["api_key"] == "mock_key_2"


@patch("app.llm_service.acompletion")
def test_key1_500_failover_to_key2_success(mock_acompletion, client: TestClient):
    """When key_1 returns 500 InternalServerError, falls over to key_2 with fallback_attempts=1."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Recovered after 500"))]
    mock_resp.model = settings.LLM_MODEL
    mock_resp.usage = MagicMock(prompt_tokens=18, completion_tokens=4)
    mock_resp._hidden_params = {}

    server_exc = litellm.InternalServerError(
        message="500 internal error", llm_provider="gemini", model=settings.LLM_MODEL
    )
    mock_acompletion.side_effect = [server_exc, mock_resp]

    response = client.post(
        "/chat",
        json={"session_id": "s-500-failover", "message": "Test 500 failover"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert mock_acompletion.call_count == 2


@patch("app.llm_service.acompletion")
def test_all_keys_fail_returns_503_and_no_db_writes(mock_acompletion, client: TestClient):
    """When every key fails, returns 503 {"detail": "all providers unavailable"} and writes nothing."""
    exc_1 = litellm.RateLimitError(
        message="429", llm_provider="gemini", model=settings.LLM_MODEL
    )
    exc_2 = litellm.ServiceUnavailableError(
        message="503", llm_provider="gemini", model=settings.LLM_MODEL
    )
    mock_acompletion.side_effect = [exc_1, exc_2]

    response = client.post(
        "/chat",
        json={"session_id": "s-all-fail", "message": "All keys down"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert mock_acompletion.call_count == 2

    # Ensure zero DB writes
    hist = client.get("/sessions/s-all-fail/messages")
    assert hist.status_code == 404
    assert hist.json() == {"detail": "session not found"}


@patch("app.llm_service.acompletion")
def test_simulation_disabled_ignores_header(mock_acompletion, client: TestClient, monkeypatch):
    """When ENABLE_FAILURE_SIMULATION=false, X-Simulate-Failure is ignored."""
    monkeypatch.setattr(settings, "ENABLE_FAILURE_SIMULATION", False)

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Normal key_1 reply"))]
    mock_resp.model = settings.LLM_MODEL
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=4)
    mock_resp._hidden_params = {}
    mock_acompletion.return_value = mock_resp

    response = client.post(
        "/chat",
        json={"session_id": "s-sim-disabled", "message": "Hello"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"
    assert response.json()["metadata"]["fallback_attempts"] == 0


@patch("app.llm_service.acompletion")
def test_simulation_enabled_key1_failover_and_all_fail(
    mock_acompletion, client: TestClient, monkeypatch
):
    """When ENABLE_FAILURE_SIMULATION=true, simulates key_1=429/500 failover and *=429 503."""
    monkeypatch.setattr(settings, "ENABLE_FAILURE_SIMULATION", True)

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Real fallback reply from key_2"))]
    mock_resp.model = settings.LLM_MODEL
    mock_resp.usage = MagicMock(prompt_tokens=14, completion_tokens=6)
    mock_resp._hidden_params = {}
    mock_acompletion.return_value = mock_resp

    # key_1=429 -> key_2 succeeds
    res1 = client.post(
        "/chat",
        json={"session_id": "s-sim-1", "message": "Test sim 429"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert res1.status_code == 200
    assert res1.json()["metadata"]["key_id"] == "key_2"
    assert res1.json()["metadata"]["fallback_attempts"] == 1
    assert mock_acompletion.call_args.kwargs["api_key"] == "mock_key_2"

    # key_1=500 -> key_2 succeeds
    res2 = client.post(
        "/chat",
        json={"session_id": "s-sim-2", "message": "Test sim 500"},
        headers={"X-Simulate-Failure": "key_1=500"},
    )
    assert res2.status_code == 200
    assert res2.json()["metadata"]["key_id"] == "key_2"
    assert res2.json()["metadata"]["fallback_attempts"] == 1

    # key_1=429,key_2=500 -> 503 and no DB write
    mock_acompletion.reset_mock()
    res3 = client.post(
        "/chat",
        json={"session_id": "s-sim-3", "message": "Test sim both"},
        headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
    )
    assert res3.status_code == 503
    assert res3.json() == {"detail": "all providers unavailable"}
    assert mock_acompletion.call_count == 0
    assert client.get("/sessions/s-sim-3/messages").status_code == 404

    # *=429 -> 503 and no DB write
    res4 = client.post(
        "/chat",
        json={"session_id": "s-sim-4", "message": "Test sim wildcard"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert res4.status_code == 503
    assert res4.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-sim-4/messages").status_code == 404

    # Unsupported status rejected with 422
    res_invalid = client.post(
        "/chat",
        json={"session_id": "s-sim-bad", "message": "Invalid status"},
        headers={"X-Simulate-Failure": "key_1=404"},
    )
    assert res_invalid.status_code == 422


def test_litellm_cache_miss_and_hit_across_sessions(client: TestClient):
    """
    Tests LiteLLM's real built-in cache end-to-end:
    - Miss on first request -> LIVE_INFERENCE, key_1
    - Hit on same first message in a new session -> LLM_CACHE, key_id=null, fallback_attempts=0
    - Identical reply, identical token counts, no provider call on cache hit, faster latency
    """
    async def delayed_gemini_post(*args, **kwargs):
        await asyncio.sleep(0.06)  # 60ms simulated provider latency
        return make_gemini_http_response(
            text="The capital of France is Paris.",
            prompt_tokens=37,
            completion_tokens=8,
        )

    with patch(
        "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post",
        side_effect=delayed_gemini_post,
    ) as mock_http:
        # 1. Cache miss in session 1
        res1 = client.post(
            "/chat",
            json={"session_id": "s-cache-a", "message": "What is the capital of France?"},
        )
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1["reply"] == "The capital of France is Paris."
        assert d1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert d1["metadata"]["key_id"] == "key_1"
        assert d1["metadata"]["fallback_attempts"] == 0
        assert d1["metadata"]["input_tokens"] == 37
        assert d1["metadata"]["output_tokens"] == 8
        assert d1["metadata"]["latency_ms"] >= 50
        assert mock_http.call_count == 1

        # 2. Same first message in a NEW session -> must hit LiteLLM cache
        res2 = client.post(
            "/chat",
            json={"session_id": "s-cache-b", "message": "What is the capital of France?"},
        )
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["reply"] == d1["reply"]
        assert d2["metadata"]["resolution_source"] == "LLM_CACHE"
        assert d2["metadata"]["key_id"] is None
        assert d2["metadata"]["fallback_attempts"] == 0
        assert d2["metadata"]["input_tokens"] == 37
        assert d2["metadata"]["output_tokens"] == 8
        assert d2["metadata"]["latency_ms"] < d1["metadata"]["latency_ms"]
        # Provider HTTP transport must NOT have been called again
        assert mock_http.call_count == 1


def test_different_messages_not_cached(client: TestClient):
    """Different messages must never collide in cache."""
    call_idx = 0

    async def dynamic_post(*args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        return make_gemini_http_response(text=f"Reply {call_idx}", prompt_tokens=10 + call_idx, completion_tokens=5)

    with patch(
        "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post",
        side_effect=dynamic_post,
    ) as mock_http:
        res1 = client.post("/chat", json={"session_id": "s-diff-1", "message": "First question"})
        res2 = client.post("/chat", json={"session_id": "s-diff-2", "message": "Second question"})

        assert res1.status_code == 200 and res1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert res2.status_code == 200 and res2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert res1.json()["reply"] != res2.json()["reply"]
        assert mock_http.call_count == 2


def test_full_conversation_context_in_cache_key(client: TestClient):
    """
    Cache key includes model + system prompt + history + current message:
    - Different system_prompt misses cache
    - Different conversation history misses cache
    - Identical full multi-turn context hits cache
    """
    call_idx = 0

    async def dynamic_post(*args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        return make_gemini_http_response(text=f"Reply {call_idx}", prompt_tokens=20 + call_idx, completion_tokens=6)

    with patch(
        "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post",
        side_effect=dynamic_post,
    ) as mock_http:
        # 1. Default system prompt -> Miss (call 1)
        r1 = client.post("/chat", json={"session_id": "s-ctx-1", "message": "Hello"})
        assert r1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

        # 2. Custom system prompt with same user message -> Miss (call 2)
        r2 = client.post(
            "/chat",
            json={"session_id": "s-ctx-2", "message": "Hello", "system_prompt": "Be a pirate."},
        )
        assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

        # 3. Follow-up message in s-ctx-1 -> Miss (call 3, history has Reply 1)
        r3 = client.post("/chat", json={"session_id": "s-ctx-1", "message": "Follow up"})
        assert r3.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

        # 4. Same follow-up in s-ctx-2 -> Miss (call 4, different system prompt & history)
        r4 = client.post(
            "/chat",
            json={"session_id": "s-ctx-2", "message": "Follow up", "system_prompt": "Be a pirate."},
        )
        assert r4.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert mock_http.call_count == 4

        # 5. New session s-ctx-3 replaying exact same turn 1 + turn 2 as s-ctx-1 -> BOTH hit cache!
        r5 = client.post("/chat", json={"session_id": "s-ctx-3", "message": "Hello"})
        assert r5.json()["metadata"]["resolution_source"] == "LLM_CACHE"
        assert r5.json()["reply"] == r1.json()["reply"]

        r6 = client.post("/chat", json={"session_id": "s-ctx-3", "message": "Follow up"})
        assert r6.json()["metadata"]["resolution_source"] == "LLM_CACHE"
        assert r6.json()["reply"] == r3.json()["reply"]
        assert mock_http.call_count == 4


def test_cache_cannot_bypass_active_failure_simulation(client: TestClient, monkeypatch):
    """
    Active X-Simulate-Failure must bypass cache reads so simulated failures
    exercise real key failover or 503 errors.
    """
    monkeypatch.setattr(settings, "ENABLE_FAILURE_SIMULATION", True)
    call_idx = 0

    async def dynamic_post(*args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        return make_gemini_http_response(text=f"Live response #{call_idx}", prompt_tokens=15, completion_tokens=5)

    with patch(
        "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post",
        side_effect=dynamic_post,
    ) as mock_http:
        # 1. Populate cache normally
        r1 = client.post("/chat", json={"session_id": "s-bypass-1", "message": "Cached prompt"})
        assert r1.status_code == 200
        assert r1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert mock_http.call_count == 1

        # 2. Normal repeat hits cache
        r2 = client.post("/chat", json={"session_id": "s-bypass-2", "message": "Cached prompt"})
        assert r2.status_code == 200
        assert r2.json()["metadata"]["resolution_source"] == "LLM_CACHE"
        assert mock_http.call_count == 1

        # 3. Same prompt with X-Simulate-Failure: key_1=429 MUST NOT return cache hit; must fall over to key_2
        r3 = client.post(
            "/chat",
            json={"session_id": "s-bypass-3", "message": "Cached prompt"},
            headers={"X-Simulate-Failure": "key_1=429"},
        )
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert d3["metadata"]["key_id"] == "key_2"
        assert d3["metadata"]["fallback_attempts"] == 1
        assert mock_http.call_count == 2

        # 4. Same prompt with X-Simulate-Failure: *=429 MUST return 503, not cache hit
        r4 = client.post(
            "/chat",
            json={"session_id": "s-bypass-4", "message": "Cached prompt"},
            headers={"X-Simulate-Failure": "*=429"},
        )
        assert r4.status_code == 503
        assert r4.json() == {"detail": "all providers unavailable"}
        assert client.get("/sessions/s-bypass-4/messages").status_code == 404


def test_session_isolation_and_history_endpoint(client: TestClient, isolated_test_env: str):
    """Verify multi-turn persistence, session isolation, and GET /sessions/{id}/messages."""
    async def mock_post(*args, **kwargs):
        return make_gemini_http_response(text="Mocked answer", prompt_tokens=30, completion_tokens=7)

    with patch("litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post", side_effect=mock_post):
        client.post("/chat", json={"session_id": "s-iso-1", "message": "Msg A1"})
        client.post("/chat", json={"session_id": "s-iso-2", "message": "Msg B1"})
        client.post("/chat", json={"session_id": "s-iso-1", "message": "Msg A2"})

    h1 = client.get("/sessions/s-iso-1/messages")
    assert h1.status_code == 200
    msgs1 = h1.json()["messages"]
    assert len(msgs1) == 4
    assert msgs1[0] == {"role": "user", "content": "Msg A1"}
    assert msgs1[1]["role"] == "assistant"
    assert msgs1[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert msgs1[2] == {"role": "user", "content": "Msg A2"}

    h2 = client.get("/sessions/s-iso-2/messages")
    assert h2.status_code == 200
    assert len(h2.json()["messages"]) == 2
    assert h2.json()["messages"][0]["content"] == "Msg B1"


def test_unknown_session_returns_404(client: TestClient):
    """GET /sessions/{session_id}/messages returns 404 for unknown sessions."""
    response = client.get("/sessions/s-unknown-404/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}
