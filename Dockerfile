FROM python:3.12-slim

# System deps for tree-sitter compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system .

# Copy application source
COPY src/ ./src/

# Action entrypoint: reads env vars and calls mergeguard review
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
