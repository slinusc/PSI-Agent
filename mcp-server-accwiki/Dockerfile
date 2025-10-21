FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY mcp-server-accwiki/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - new accwiki_mcp package structure
COPY mcp-server-accwiki/accwiki_mcp /app/accwiki_mcp

# Create model cache directory
RUN mkdir -p /root/.cache/huggingface

# Run the MCP HTTP server
CMD ["python3", "-m", "accwiki_mcp.server"]
