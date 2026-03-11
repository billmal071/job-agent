"""Token bucket rate limiter with circuit breaker pattern."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from job_agent.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class TokenBucket:
    """Token bucket rate limiter.

    Args:
        rate: Tokens added per second.
        capacity: Maximum tokens in the bucket.
    """

    rate: float
    capacity: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if successful."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait(self, tokens: float = 1.0) -> None:
        """Block until tokens are available, then consume them."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait_time = (tokens - self._tokens) / self.rate
            time.sleep(wait_time)


class CircuitBreaker:
    """Circuit breaker that opens after consecutive failures.

    States:
        CLOSED: Normal operation, requests pass through.
        OPEN: Failures exceeded threshold, requests are blocked.
        HALF_OPEN: After cooldown, allow one test request.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 1800.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                    self._state = self.HALF_OPEN
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed."""
        current = self.state
        if current == self.CLOSED:
            return True
        if current == self.HALF_OPEN:
            return True
        log.warning(
            "circuit_breaker_open",
            failures=self._failure_count,
            cooldown_remaining=max(
                0,
                self.cooldown_seconds - (time.monotonic() - self._last_failure_time),
            ),
        )
        return False

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                log.warning(
                    "circuit_breaker_tripped",
                    failures=self._failure_count,
                    cooldown=self.cooldown_seconds,
                )


class RateLimiter:
    """Combined rate limiter with token bucket and circuit breaker."""

    def __init__(
        self,
        requests_per_minute: float,
        failure_threshold: int = 5,
        cooldown_seconds: float = 1800.0,
    ):
        self.bucket = TokenBucket(
            rate=requests_per_minute / 60.0,
            capacity=requests_per_minute,
        )
        self.circuit = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )

    def acquire(self) -> bool:
        """Try to acquire permission for a request."""
        if not self.circuit.allow_request():
            return False
        return self.bucket.acquire()

    def wait(self) -> bool:
        """Wait for rate limit, but respect circuit breaker."""
        if not self.circuit.allow_request():
            return False
        self.bucket.wait()
        return True

    def success(self) -> None:
        self.circuit.record_success()

    def failure(self) -> None:
        self.circuit.record_failure()
