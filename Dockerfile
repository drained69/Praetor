# Praetor — production image.
# Python 3.12 keeps the optional virtuals-acp SDK installable (<3.13).
FROM python:3.12-slim

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0

# Node.js + the official Virtuals ACP CLI. The CLI is the preferred Virtuals
# backend — it works with any Virtuals-registered agent + whitelisted signer
# and does not require an ACP v2 smart account deploy on the agent wallet.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @virtuals-protocol/acp-cli \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/*

# Python deps first for better layer caching.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[server,virtuals]" sibyl-memory-client

# Railway provides $PORT at runtime; the server reads it (defaults to 8000).
EXPOSE 8000
CMD ["praetor-server"]
