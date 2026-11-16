"""Resilience primitives: Circuit Breaker, Timeout (8s), and Exponential Backoff with Jitter."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")


class CircuitBreakerOpenError(RuntimeError):
    """Raised when the Circuit Breaker is in OPEN state and fast-fails."""


class CircuitBreaker:
    """Thread-safe state machine (CLOSED -> OPEN -> HALF_OPEN) protecting external LLM calls."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        call_timeout_seconds: float = 8.0,
        max_retries: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.call_timeout_seconds = call_timeout_seconds
        self.max_retries = max_retries
        self._failure_count = 0
        self._state = "CLOSED"
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        if (
            self._state == "OPEN"
            and (time.monotonic() - self._opened_at) >= self.recovery_timeout_seconds
        ):
            self._state = "HALF_OPEN"
        return self._state

    def execute(self, func: Callable[[], T]) -> T:
        """Execute `func` with Circuit Breaker, Retry with Backoff, and hard 8s Timeout."""
        current_state = self.state
        if current_state == "OPEN":
            raise CircuitBreakerOpenError("Gemini LLM Circuit Breaker is OPEN")

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential_jitter(initial=0.05, max=0.5),
            retry=retry_if_not_exception_type(CircuitBreakerOpenError),
            reraise=True,
        )
        def _attempt_with_timeout() -> T:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func)
                try:
                    return future.result(timeout=self.call_timeout_seconds)
                except FuturesTimeoutError as exc:
                    raise TimeoutError(
                        f"LLM call exceeded timeout of {self.call_timeout_seconds}s"
                    ) from exc

        try:
            result = _attempt_with_timeout()
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        self._failure_count = 0
        self._state = "CLOSED"

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            self._opened_at = time.monotonic()
