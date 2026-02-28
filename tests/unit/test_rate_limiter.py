"""Tests for rate limiter and circuit breaker."""

from job_agent.utils.rate_limiter import CircuitBreaker, RateLimiter, TokenBucket


def test_token_bucket_acquire():
    bucket = TokenBucket(rate=10.0, capacity=10.0)
    # Should succeed with full bucket
    assert bucket.acquire(1.0)
    assert bucket.acquire(1.0)


def test_token_bucket_exhaust():
    bucket = TokenBucket(rate=1.0, capacity=2.0)
    assert bucket.acquire(2.0)
    # Bucket is empty
    assert not bucket.acquire(1.0)


def test_circuit_breaker_closed():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request()


def test_circuit_breaker_opens():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert not cb.allow_request()


def test_circuit_breaker_success_resets():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED


def test_rate_limiter_integration():
    limiter = RateLimiter(requests_per_minute=60, failure_threshold=5)
    assert limiter.acquire()
    limiter.success()
