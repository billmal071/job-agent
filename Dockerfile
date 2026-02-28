FROM python:3.11-slim AS base

# Install system dependencies for weasyprint and playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY alembic.ini ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Install Playwright browsers
RUN uv run playwright install chromium --with-deps

# Create non-root user
RUN useradd -m -s /bin/bash agent
USER agent

# Create data directory
RUN mkdir -p /home/agent/.job-agent

EXPOSE 5000

ENTRYPOINT ["uv", "run", "job-agent"]
CMD ["dashboard"]
