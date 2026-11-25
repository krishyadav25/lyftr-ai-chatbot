import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import litellm
from litellm import acompletion
from litellm.caching.caching import Cache
from litellm.types.caching import LiteLLMCacheType

from app.config import settings

logger = logging.getLogger(__name__)

# Suppress extraneous external telemetry
litellm.telemetry = False
litellm.drop_params = True

ALLOWED_SIMULATION_STATUSES = {429, 500, 502, 503}


class LLMServiceError(Exception):
    """Raised when LLM inference fails across all available keys."""

    pass


def init_llm_cache() -> bool:
    """
    Initialize LiteLLM's built-in local in-memory cache.
    Sets max_messages=None so multi-turn conversations of any length remain cacheable.
    """
    try:
        litellm.cache = Cache(type=LiteLLMCacheType.LOCAL, max_messages=None)
        return True
    except Exception as exc:
        logger.error("Failed to initialize LiteLLM cache: %s", type(exc).__name__)
        litellm.cache = None
        return False


def is_cache_enabled() -> bool:
    """Return True only when LiteLLM built-in caching is initialized."""
    return litellm.cache is not None


def parse_simulate_failure_header(header_value: Optional[str]) -> Dict[str, int]:
    """
    Parse X-Simulate-Failure header (e.g., 'key_1=429,key_2=500' or '*=429').
    Honored only when ENABLE_FAILURE_SIMULATION=true.
    Accepts only HTTP statuses 429, 500, 502, 503.
    """
    if not settings.ENABLE_FAILURE_SIMULATION or not header_value or not header_value.strip():
        return {}

    rules: Dict[str, int] = {}
    for raw_pair in header_value.split(","):
        pair = raw_pair.strip()
        if not pair:
            raise ValueError("Empty rule in X-Simulate-Failure header")
        if "=" not in pair:
            raise ValueError(
                f"Malformed X-Simulate-Failure rule '{pair}'; expected <key_id|*>=<status>"
            )
        target, status_str = pair.split("=", 1)
        target = target.strip()
        status_str = status_str.strip()
        if not target:
            raise ValueError("Missing key identifier in X-Simulate-Failure rule")
        if not status_str.isdigit():
            raise ValueError(f"Non-numeric status '{status_str}' in X-Simulate-Failure")
        status_code = int(status_str)
        if status_code not in ALLOWED_SIMULATION_STATUSES:
            raise ValueError(
                f"Unsupported failure simulation status {status_code}; allowed: 429, 500, 502, 503"
            )
        rules[target] = status_code
    return rules


def is_retryable_provider_error(exc: Exception) -> bool:
    """
    Return True for HTTP 429, quota exhaustion, or retryable 5xx provider failures.
    """
    retryable_types = (
        litellm.RateLimitError,
        litellm.ServiceUnavailableError,
        litellm.InternalServerError,
        litellm.BadGatewayError,
        litellm.Timeout,
        litellm.APIConnectionError,
    )
    if isinstance(exc, retryable_types):
        return True

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (status_code == 429 or 500 <= status_code < 600):
        return True

    err_msg = str(exc).lower()
    retryable_markers = (
        "429",
        "rate limit",
        "rate_limit",
        "quota",
        "resource exhausted",
        "resource_exhausted",
        "500",
        "502",
        "503",
        "504",
        "service unavailable",
        "internal server error",
        "bad gateway",
        "overloaded",
    )
    return any(marker in err_msg for marker in retryable_markers)


class LLMService:
    """Service handling LLM completion calls with multi-key failover and LiteLLM caching."""

    def get_key_pool_entries(self) -> List[tuple[str, str]]:
        """
        Returns ordered [(key_id, api_key), ...] pairs as key_1, key_2, ...
        """
        keys = settings.get_key_pool()
        if not keys:
            raise LLMServiceError("No API keys configured")
        return [(f"key_{idx + 1}", key) for idx, key in enumerate(keys)]

    async def generate_reply(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        simulated_failures: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Execute asynchronous completion via LiteLLM with:
        - Automatic key failover across LLM_API_KEYS on 429, quota, or 5xx errors
        - Per-request failure simulation isolation (bypassing cache hits when active)
        - Built-in LiteLLM response caching and reliable cache hit detection
        """
        key_entries = self.get_key_pool_entries()
        target_model = model or settings.LLM_MODEL
        sim_rules = simulated_failures or {}
        simulation_active = bool(sim_rules)

        start_time = time.perf_counter()
        failed_attempts = 0

        for key_id, api_key in key_entries:
            # Check per-request failure simulation before attempting provider call
            sim_status = sim_rules.get(key_id)
            if sim_status is None:
                sim_status = sim_rules.get("*")

            if sim_status is not None:
                logger.warning("Simulated %d failure triggered for %s", sim_status, key_id)
                failed_attempts += 1
                continue

            call_kwargs: Dict[str, Any] = {
                "model": target_model,
                "messages": messages,
                "api_key": api_key,
            }
            # Ensure cache hits cannot bypass an active failure simulation
            if simulation_active:
                call_kwargs["cache"] = {"no-cache": True, "no-store": True}

            try:
                response = await acompletion(**call_kwargs)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                reply = response.choices[0].message.content
                if not reply:
                    reply = ""

                usage = getattr(response, "usage", None)
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

                model_name = getattr(response, "model", None) or target_model

                # Reliable LiteLLM cache hit detection via _hidden_params["cache_hit"]
                hidden_params = getattr(response, "_hidden_params", None) or {}
                is_cache_hit = bool(hidden_params.get("cache_hit") is True)

                if is_cache_hit:
                    resolution_source = "LLM_CACHE"
                    resolved_key_id: Optional[str] = None
                    resolved_fallback_attempts = 0
                else:
                    resolution_source = "LIVE_INFERENCE"
                    resolved_key_id = key_id
                    resolved_fallback_attempts = failed_attempts
                    # Yield once so LiteLLM's background cache write task commits immediately
                    if is_cache_enabled() and not simulation_active:
                        await asyncio.sleep(0)

                metadata = {
                    "resolution_source": resolution_source,
                    "model": model_name,
                    "latency_ms": elapsed_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": resolved_key_id,
                    "fallback_attempts": resolved_fallback_attempts,
                }

                return {
                    "reply": reply,
                    "metadata": metadata,
                }
            except Exception as exc:
                # Never log api_key or secrets
                logger.warning(
                    "LiteLLM completion failure on %s: %s", key_id, type(exc).__name__
                )
                if is_retryable_provider_error(exc):
                    failed_attempts += 1
                    continue
                raise LLMServiceError(
                    f"Non-retryable provider error on {key_id}: {type(exc).__name__}"
                ) from exc

        raise LLMServiceError("All providers unavailable")


llm_service = LLMService()
