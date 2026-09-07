# Sibyl Relay — production image for Railway / any container host.
# Python 3.12 keeps the optional virtuals-acp SDK installable (<3.13).
FROM python:3.12-slim

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[server]" sibyl-memory-client

# Railway provides $PORT at runtime; the server reads it (defaults to 8000).
EXPOSE 8000
CMD ["sibyl-relay-server"]
