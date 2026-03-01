"""Shared test fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock

from job_agent.config import Settings
from job_agent.db.models import Base


@pytest.fixture
def settings():
    """Test settings with in-memory SQLite."""
    s = Settings(
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )
    return s


@pytest.fixture
def db_session(settings):
    """Create an in-memory database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def mock_page():
    """A MagicMock standing in for a Playwright Page."""
    page = MagicMock()
    page.url = "https://example.com/job/123"
    page.is_closed.return_value = False

    # Default locator behaviour: nothing found
    locator = MagicMock()
    locator.count.return_value = 0
    page.locator.return_value = locator

    return page


@pytest.fixture
def mock_rate_limiter():
    """A MagicMock standing in for RateLimiter."""
    rl = MagicMock()
    rl.wait.return_value = True  # circuit breaker closed by default
    return rl
