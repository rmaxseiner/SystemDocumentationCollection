# Dockerfile for Infrastructure Documentation Collection
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    openssh-client \
    curl \
    jq \
    ca-certificates \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY infrastructure_pipeline.py .

# Create directories for outputs and SSH
RUN mkdir -p /app/rag_output \
             /app/collected_data \
             /app/logs \
             /app/.ssh \
    && chmod 700 /app/.ssh

# Copy entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Health check - verify pipeline exists and is executable
HEALTHCHECK --interval=10m --timeout=30s --start-period=2m --retries=3 \
    CMD test -f /app/infrastructure_pipeline.py || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["schedule"]