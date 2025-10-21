#!/bin/bash
# MCP Servers Management Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

usage() {
    echo -e "${BLUE}MCP Servers Management Script${NC}"
    echo ""
    echo "Usage: $0 {start|stop|restart|rebuild|logs|status|health}"
    echo ""
    echo "Commands:"
    echo "  start      - Start all MCP servers and dependencies"
    echo "  stop       - Stop all services"
    echo "  restart    - Restart all services"
    echo "  rebuild    - Rebuild and restart all MCP servers (not dependencies)"
    echo "  logs       - Show logs from all services (use -f to follow)"
    echo "  status     - Show running status of all services"
    echo "  health     - Check health of all MCP servers"
    echo ""
    echo "Individual server commands:"
    echo "  rebuild-elog     - Rebuild only ELOG server"
    echo "  rebuild-accwiki  - Rebuild only AccWiki server"
    echo "  rebuild-websearch - Rebuild only WebSearch server"
    echo ""
    exit 1
}

start() {
    echo -e "${GREEN}Starting all MCP servers...${NC}"
    docker compose up -d
    echo -e "${GREEN}✓ All services started${NC}"
    echo ""
    status
}

stop() {
    echo -e "${YELLOW}Stopping all services...${NC}"
    docker compose down
    echo -e "${GREEN}✓ All services stopped${NC}"
}

restart() {
    echo -e "${YELLOW}Restarting all services...${NC}"
    docker compose restart
    echo -e "${GREEN}✓ All services restarted${NC}"
}

rebuild() {
    echo -e "${BLUE}Rebuilding all MCP servers...${NC}"
    echo -e "${YELLOW}Stopping MCP servers...${NC}"
    docker compose stop mcp-server-elog mcp-server-accwiki mcp-server-websearch

    echo -e "${BLUE}Rebuilding ELOG server...${NC}"
    docker compose build --no-cache mcp-server-elog

    echo -e "${BLUE}Rebuilding AccWiki server...${NC}"
    docker compose build --no-cache mcp-server-accwiki

    echo -e "${BLUE}Rebuilding WebSearch server...${NC}"
    docker compose build --no-cache mcp-server-websearch

    echo -e "${YELLOW}Starting MCP servers...${NC}"
    docker compose up -d mcp-server-elog mcp-server-accwiki mcp-server-websearch

    echo -e "${GREEN}✓ All MCP servers rebuilt and started${NC}"
    echo ""
    echo "Waiting for services to be healthy..."
    sleep 5
    health
}

rebuild_elog() {
    echo -e "${BLUE}Rebuilding ELOG server...${NC}"
    docker compose stop mcp-server-elog
    docker compose build --no-cache mcp-server-elog
    docker compose up -d mcp-server-elog
    echo -e "${GREEN}✓ ELOG server rebuilt${NC}"
}

rebuild_accwiki() {
    echo -e "${BLUE}Rebuilding AccWiki server...${NC}"
    docker compose stop mcp-server-accwiki
    docker compose build --no-cache mcp-server-accwiki
    docker compose up -d mcp-server-accwiki
    echo -e "${GREEN}✓ AccWiki server rebuilt${NC}"
}

rebuild_websearch() {
    echo -e "${BLUE}Rebuilding WebSearch server...${NC}"
    docker compose stop mcp-server-websearch
    docker compose build --no-cache mcp-server-websearch
    docker compose up -d mcp-server-websearch
    echo -e "${GREEN}✓ WebSearch server rebuilt${NC}"
}

logs() {
    if [ "$2" == "-f" ]; then
        docker compose logs -f
    else
        docker compose logs --tail=50
    fi
}

status() {
    echo -e "${BLUE}Service Status:${NC}"
    docker compose ps
}

health() {
    echo -e "${BLUE}Health Check:${NC}"
    echo ""

    # ELOG
    echo -n "ELOG (8002):      "
    if curl -sf http://localhost:8002/healthz > /dev/null; then
        echo -e "${GREEN}✓ Healthy${NC}"
    else
        echo -e "${RED}✗ Unhealthy${NC}"
    fi

    # AccWiki
    echo -n "AccWiki (8001):   "
    if curl -sf http://localhost:8001/healthz > /dev/null; then
        echo -e "${GREEN}✓ Healthy${NC}"
    else
        echo -e "${RED}✗ Unhealthy${NC}"
    fi

    # WebSearch
    echo -n "WebSearch (8003): "
    if curl -sf http://localhost:8003/healthz > /dev/null; then
        echo -e "${GREEN}✓ Healthy${NC}"
    else
        echo -e "${RED}✗ Unhealthy${NC}"
    fi

    # Neo4j
    echo -n "Neo4j (7474):     "
    if curl -sf http://localhost:7474 > /dev/null; then
        echo -e "${GREEN}✓ Healthy${NC}"
    else
        echo -e "${RED}✗ Unhealthy${NC}"
    fi

    # SearXNG
    echo -n "SearXNG (8888):   "
    if curl -sf http://localhost:8888 > /dev/null; then
        echo -e "${GREEN}✓ Healthy${NC}"
    else
        echo -e "${RED}✗ Unhealthy${NC}"
    fi

    echo ""
}

# Main command dispatcher
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    rebuild)
        rebuild
        ;;
    rebuild-elog)
        rebuild_elog
        ;;
    rebuild-accwiki)
        rebuild_accwiki
        ;;
    rebuild-websearch)
        rebuild_websearch
        ;;
    logs)
        logs "$@"
        ;;
    status)
        status
        ;;
    health)
        health
        ;;
    *)
        usage
        ;;
esac
