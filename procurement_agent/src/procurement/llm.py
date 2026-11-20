"""LLM access behind a small interface so tests can use a fake.

Hackathon rule: Bedrock under 1 request per second. Every Bedrock request,
including retries, goes through one process-wide RateLimiter. botocore's own
retries are switched off so they cannot bypass it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Protocol

DEFAULT_MODEL_ID = "us.amazon.nova-lite-v1:0"
MIN_INTERVAL_FLOOR = 1.05  # seconds; never allow 1 request/second or more
RETRYABLE_ERRORS = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException",
                    "InternalServerException"}

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    def converse(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        force_tool: str | None = None,
    ) -> dict:
        """Return a Bedrock Converse-shaped response dict."""
        ...


class RateLimiter:
    """Allows at most one call per `min_interval` seconds across all threads."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval = max(float(min_interval), MIN_INTERVAL_FLOOR)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = float("-inf")

    def acquire(self) -> None:
        with self._lock:  # held while sleeping so callers queue up in order
            wait = self._next_allowed - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._next_allowed = self._clock() + self.min_interval


def _interval_from_env() -> float:
    try:
        return float(os.getenv("BEDROCK_MIN_INTERVAL_SECONDS", "1.2"))
    except ValueError:
        return 1.2


# One limiter per process: Streamlit sessions and agent instances all share it.
_SHARED_LIMITER = RateLimiter(_interval_from_env())


class LLMServiceError(RuntimeError):
    """Bedrock failed after retries. The message is safe to show to users."""


class BedrockClient:
    def __init__(self, model_id: str | None = None, region: str | None = None, client=None,
                 limiter: RateLimiter | None = None, max_attempts: int = 4,
                 sleep: Callable[[float], None] = time.sleep):
        self.model_id = model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
        self._limiter = limiter or _SHARED_LIMITER
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        if client is None:
            import boto3  # imported lazily so tests do not need AWS config
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime",
                region_name=region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
                # Retries are done below, through the rate limiter.
                config=Config(retries={"total_max_attempts": 1}, read_timeout=60, connect_timeout=10),
            )
        self._client = client

    def converse(self, system, messages, tools=None, force_tool=None):
        kwargs: dict = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": 1024, "temperature": 0.0},
        }
        if tools:
            tool_config: dict = {"tools": tools}
            if force_tool:
                tool_config["toolChoice"] = {"tool": {"name": force_tool}}
            kwargs["toolConfig"] = tool_config

        for attempt in range(1, self._max_attempts + 1):
            self._limiter.acquire()
            try:
                return self._client.converse(**kwargs)
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
                if code not in RETRYABLE_ERRORS or attempt == self._max_attempts:
                    if code in RETRYABLE_ERRORS:
                        raise LLMServiceError(
                            "The AI service is busy. Please wait a moment and try again.") from exc
                    raise
                backoff = 2 ** attempt  # 2, 4, 8 s, on top of the rate limit
                log.warning("Bedrock %s on attempt %d; retrying in %ss", code, attempt, backoff)
                self._sleep(backoff)
        raise AssertionError("unreachable")
