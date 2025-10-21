# MCP Servers Management

This project includes 3 MCP (Model Context Protocol) servers for the PSI-Agent:

1. **ELOG** (port 8002) - SwissFEL electronic logbook integration
2. **AccWiki** (port 8001) - PSI Accelerator Knowledge Graph
3. **WebSearch** (port 8003) - Web search via SearXNG

## Quick Start

### Start All Services
```bash
./mcp-servers.sh start
```

### Check Health
```bash
./mcp-servers.sh health
```

### Rebuild After Code Changes
```bash
./mcp-servers.sh rebuild
```

## Available Commands

### Management Commands
```bash
./mcp-servers.sh start      # Start all services
./mcp-servers.sh stop       # Stop all services
./mcp-servers.sh restart    # Restart all services
./mcp-servers.sh rebuild    # Rebuild and restart MCP servers
./mcp-servers.sh logs       # View logs (add -f to follow)
./mcp-servers.sh status     # Show running status
./mcp-servers.sh health     # Check health endpoints
```

### Individual Server Rebuilds
```bash
./mcp-servers.sh rebuild-elog        # Rebuild only ELOG
./mcp-servers.sh rebuild-accwiki     # Rebuild only AccWiki
./mcp-servers.sh rebuild-websearch   # Rebuild only WebSearch
```

## Service URLs

| Service | Port | Health Check | Description |
|---------|------|--------------|-------------|
| ELOG MCP | 8002 | http://localhost:8002/healthz | ELOG integration |
| AccWiki MCP | 8001 | http://localhost:8001/healthz | Knowledge graph |
| WebSearch MCP | 8003 | http://localhost:8003/healthz | Web search |
| Neo4j | 7474, 7687 | http://localhost:7474 | Graph database |
| SearXNG | 8888 | http://localhost:8888 | Search engine |

## Architecture

```
┌─────────────────────────────────────────────┐
│            PSI-Agent (LangGraph)            │
│                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐    │
│  │  ELOG   │  │ AccWiki │  │WebSearch│    │
│  │  :8002  │  │  :8001  │  │  :8003  │    │
│  └────┬────┘  └────┬────┘  └────┬────┘    │
└───────┼───────────┼────────────┼──────────┘
        │           │            │
        │           │            │
   ┌────▼──┐   ┌───▼───┐   ┌───▼──────┐
   │ ELOG  │   │ Neo4j │   │ SearXNG  │
   │  API  │   │ :7687 │   │  :8888   │
   └───────┘   └───────┘   └──────────┘
```

## Development Workflow

### After Modifying Server Code

1. **Rebuild affected server**:
   ```bash
   ./mcp-servers.sh rebuild-elog  # if you changed ELOG code
   ```

2. **Check if healthy**:
   ```bash
   ./mcp-servers.sh health
   ```

3. **View logs if issues**:
   ```bash
   ./mcp-servers.sh logs -f
   ```

### After Modifying All Servers

```bash
# Rebuild everything
./mcp-servers.sh rebuild

# Or use docker-compose directly
docker-compose build --no-cache
docker-compose up -d
```

## Volume Mounts

The docker-compose uses volume mounts for hot-reloading:

- **ELOG**: `server.py`, `elog_tools.py`, `elog_constants.py`, `logbook.py`
- **AccWiki**: `server.py`, `query_knowledge_graph.py`, `embeddings.py`
- **WebSearch**: Entire build context (no volume mounts)

This means changes to ELOG and AccWiki Python files are reflected immediately without rebuild (just restart the container).

## Dependencies

### Required Docker Volumes (External)

The Neo4j volumes must exist before starting:

```bash
docker volume create knowledge_graph_rag_neo4j_data
docker volume create knowledge_graph_rag_neo4j_logs
docker volume create knowledge_graph_rag_neo4j_import
docker volume create knowledge_graph_rag_neo4j_plugins
```

### Required Environment Variables

Create a `.env` file if needed:

```bash
# Optional overrides
ELOG_URL=https://elog-gfa.psi.ch/SwissFEL+commissioning/
HF_TOKEN=your_huggingface_token  # for AccWiki embeddings
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
./mcp-servers.sh logs -f

# Check status
docker-compose ps

# Restart specific service
docker-compose restart mcp-server-elog
```

### Port Already in Use

```bash
# Check what's using the port
sudo lsof -i :8002  # ELOG
sudo lsof -i :8001  # AccWiki
sudo lsof -i :8003  # WebSearch
```

### Neo4j Connection Issues

```bash
# Ensure Neo4j is running
docker-compose ps neo4j

# Check Neo4j logs
docker-compose logs neo4j

# Verify volumes exist
docker volume ls | grep neo4j
```

### AccWiki GPU Issues

If you don't have NVIDIA GPU, edit `docker-compose.yml` and remove the `deploy` section from `mcp-server-accwiki`.

## Testing MCP Servers

### ELOG
```bash
curl -X POST http://localhost:8002/api/search_elog \
  -H "Content-Type: application/json" \
  -d '{"query": "beam dump", "max_results": 5}'
```

### AccWiki
```bash
curl -X POST http://localhost:8001/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "buncher", "accelerator": "hipa", "limit": 3}'
```

### WebSearch
```bash
curl -X POST http://localhost:8003/api/quick_search \
  -H "Content-Type: application/json" \
  -d '{"query": "CERN accelerator"}'
```

## Useful Docker Commands

```bash
# View all containers
docker-compose ps

# Follow logs for specific service
docker-compose logs -f mcp-server-elog

# Restart specific service
docker-compose restart mcp-server-accwiki

# Stop and remove all containers
docker-compose down

# Remove all data (careful!)
docker-compose down -v
```
