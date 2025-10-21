#!/bin/bash
# Start all PSI-Agent services

set -e

echo "🚀 Starting PSI-Agent Stack..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "✓ Created .env file. Please review and update if needed."
    echo ""
fi

# Build and start all services
echo "📦 Building and starting all services..."
docker compose up -d --build

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check health
echo ""
echo "🏥 Health Check:"
echo ""

check_service() {
    local name=$1
    local port=$2
    local endpoint=${3:-/healthz}

    if curl -sf http://localhost:${port}${endpoint} > /dev/null 2>&1; then
        echo "  ✓ $name (${port})"
    else
        echo "  ✗ $name (${port}) - Not healthy"
    fi
}

check_service "Chainlit App     " 8000 /health
check_service "AccWiki MCP      " 8001
check_service "ELOG MCP         " 8002
check_service "WebSearch MCP    " 8003
check_service "Neo4j            " 7474 /
check_service "SearXNG          " 8888 /

echo ""
echo "✓ All services started!"
echo ""
echo "📍 Access Points:"
echo "   Chainlit UI:  http://localhost:8000"
echo "   Neo4j UI:     http://localhost:7474"
echo "   SearXNG:      http://localhost:8888"
echo ""
echo "📊 View logs with: docker compose logs -f [service-name]"
echo "   Services: chainlit-app, mcp-server-elog, mcp-server-accwiki, mcp-server-websearch"
echo ""
