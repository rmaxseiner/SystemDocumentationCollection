
# Dockerfile for Infrastructure Documentation Container
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    openssh-client \
    curl \
    jq \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app user and directory
RUN useradd -m -u 1000 infrauser
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Create directories for data and logs
RUN mkdir -p /app/data /app/logs /app/.ssh && \
    chown -R infrauser:infrauser /app

# Switch to non-root user
USER infrauser

# Set up cron jobs
COPY crontab /tmp/crontab
RUN crontab /tmp/crontab

# Health check
HEALTHCHECK --interval=5m --timeout=30s --start-period=5m --retries=3 \
    CMD python3 /app/src/health_check.py

# Default command runs the scheduler
CMD ["python3", "/app/src/scheduler.py"]