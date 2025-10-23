FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --no-cache-dir --upgrade pip

# Copy requirements first for better caching
COPY mcp-server-elog/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - new elog_mcp package structure
COPY mcp-server-elog/elog_mcp /app/elog_mcp

# Run the MCP HTTP server
CMD ["python3", "-m", "elog_mcp.server"]
