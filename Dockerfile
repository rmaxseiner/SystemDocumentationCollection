FROM python:3.11-slim

LABEL maintainer="Infrastructure Documentation Collection"
LABEL description="Automated infrastructure documentation collection and RAG processing"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for outputs and SSH keys
RUN mkdir -p /app/rag_output \
    /app/work/collected \
    /app/logs \
    /root/.ssh

# Set proper permissions for SSH directory
RUN chmod 700 /root/.ssh

# Default command - run the full pipeline
CMD ["python3", "infrastructure_pipeline.py"]
