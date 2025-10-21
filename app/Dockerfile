FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY app/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir langgraph langgraph-checkpoint-postgres

# Copy application code
COPY app/ /app/

# Create necessary directories
RUN mkdir -p /app/data/uploads /app/logs /app/.chainlit

# Expose Chainlit port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run Chainlit with debug logging
ENV CHAINLIT_LOG_LEVEL=debug
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
