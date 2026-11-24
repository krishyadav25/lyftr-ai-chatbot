from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import check_db_health, get_session_messages, init_db
from app.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistoryResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup."""
    await init_db()
    yield


app = FastAPI(
    title="Lyftr AI Chatbot API",
    description="LLM Chatbot with Key Failover and Response Caching",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler: Ensure all validation errors return JSON with a 'detail' field
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(exc.errors())},
    )


# Exception handler: Ensure HTTPExceptions return JSON with a 'detail' field
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# Exception handler: Catch-all to prevent internal stack traces or HTML error pages
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    responses={
        200: {"description": "App running, DB reachable, and key pool loaded."},
        503: {"description": "DB unreachable or key pool not configured."},
    },
)
async def health_check():
    """
    Returns 200 once the app is running, the database is reachable, and at least
    2 API keys are configured in the pool.
    """
    db_ok = await check_db_health()
    keys = settings.get_key_pool()
    keys_count = len(keys)

    # Health check requires reachable database and at least 2 configured keys
    if not db_ok or keys_count < 2:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "keys_configured": keys_count,
                "cache_enabled": False,
                "detail": (
                    "Database unreachable"
                    if not db_ok
                    else "Key pool not configured (minimum 2 keys required)"
                ),
            },
        )

    return HealthResponse(
        status="ok",
        keys_configured=keys_count,
        cache_enabled=True,
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat endpoint with session memory, failover, and caching",
    responses={
        422: {"description": "Missing or empty message/session_id, over 4000 chars, malformed JSON"},
        503: {"description": "Every key failed or all providers unavailable"},
    },
)
async def chat_endpoint(
    request: ChatRequest,
    x_simulate_failure: Optional[str] = Header(
        None,
        alias="X-Simulate-Failure",
        description="Optional failure simulation header: e.g. key_1=429,key_2=500",
    ),
):
    """
    POST /chat endpoint.
    In Step 2: Validates the request, reads headers, and enforces failure handling.
    Until the LiteLLM gateway service is integrated in Step 3, returns 503 without storing
    any failed messages in the session history.
    """
    # Clean service boundary: LiteLLM gateway integration will be attached here.
    # Note: Requests that fail (422 or 503) MUST NOT be added to session history.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="all providers unavailable",
    )


@app.get(
    "/sessions/{session_id}/messages",
    response_model=SessionHistoryResponse,
    response_model_exclude_none=True,
    summary="Get stored history of one session from SQLite",
    responses={
        200: {"description": "Stored history oldest first"},
        404: {"description": "Unknown session"},
    },
)
async def get_session_history(session_id: str):
    """
    Returns stored history of one session from SQLite, oldest first, without the system prompt.
    Returns 404 with {"detail": "session not found"} if the session has no recorded messages.
    """
    messages = await get_session_messages(session_id)
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    return SessionHistoryResponse(
        session_id=session_id,
        messages=messages,
    )
