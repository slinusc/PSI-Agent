# PSI-Agent Docker Setup

Complete containerized deployment of the PSI-Agent system with Chainlit UI, MCP servers, and databases.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Network (psi-network)            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐         ┌──────────────────────┐        │
│  │  Chainlit    │────────▶│  PostgreSQL          │        │
│  │  App         │         │  (State/Checkpoints) │        │
│  │  :8000       │         │  :5432               │        │
│  └──────┬───────┘         └──────────────────────┘        │
│         │                                                   │
│         │  ┌────────────────────────────────────┐         │
│         ├─▶│  MCP Server: ELOG      :8002       │         │
│         │  └────────────────────────────────────┘         │
│         │                                                   │
│         │  ┌────────────────────────────────────┐         │
│         ├─▶│  MCP Server: AccWiki   :8001       │──────┐  │
│         │  └────────────────────────────────────┘      │  │
│         │                                              │  │
│         │  ┌────────────────────────────────────┐     │  │
│         └─▶│  MCP Server: WebSearch :8003       │──┐  │  │
│            └────────────────────────────────────┘  │  │  │
│                                                     │  │  │
│            ┌────────────────────────────────────┐  │  │  │
│            │  Neo4j (Knowledge Graph)  :7687   │◀─┘  │  │
│            └────────────────────────────────────┘     │  │
│                                                        │  │
│            ┌────────────────────────────────────┐     │  │
│            │  SearXNG (Search Engine)  :8080   │◀────┘  │
│            └────────────────────────────────────┘        │
│                                                           │
│  ┌──────────────────────────────────────────────┐       │
│  │  Ollama (LLM)                                 │       │
│  │  Running on host: localhost:11434             │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| **Chainlit App** | 8000 | Web UI for PSI Assistant |
| **PostgreSQL** | 5432 | Chainlit state & LangGraph checkpoints |
| **MCP: AccWiki** | 8001 | PSI Accelerator Knowledge Graph |
| **MCP: ELOG** | 8002 | SwissFEL Electronic Logbook |
| **MCP: WebSearch** | 8003 | Web search via SearXNG |
| **Neo4j** | 7474/7687 | Graph database for AccWiki |
| **SearXNG** | 8888 | Search aggregator |

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose installed
- Ollama running on host (`localhost:11434`)
- Neo4j external volumes created (if using AccWiki):
  ```bash
  docker volume create knowledge_graph_rag_neo4j_data
  docker volume create knowledge_graph_rag_neo4j_logs
  docker volume create knowledge_graph_rag_neo4j_import
  docker volume create knowledge_graph_rag_neo4j_plugins
  ```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set:
# - CHAINLIT_ADMIN_PASSWORD
# - CHAINLIT_AUTH_SECRET (generate with: openssl rand -base64 32)
# - HF_TOKEN (if using HuggingFace models)
```

### 3. Start All Services

```bash
./start-all.sh
```

Or manually:
```bash
docker compose up -d --build
```

### 4. Access the UI

Open http://localhost:8000 in your browser.

Default credentials:
- Username: `admin@chainlit.com`
- Password: (from `.env` CHAINLIT_ADMIN_PASSWORD)

## Management Commands

### Start Services
```bash
./start-all.sh
```

### Stop Services
```bash
./stop-all.sh
```

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f chainlit-app
docker compose logs -f mcp-server-elog
docker compose logs -f postgres-chainlit
```

### Restart a Service
```bash
docker compose restart chainlit-app
docker compose restart mcp-server-accwiki
```

### Rebuild After Code Changes
```bash
# Rebuild specific service
docker compose up -d --build chainlit-app

# Rebuild all
docker compose up -d --build
```

## Data Persistence

### Volumes

**Local (managed by Docker):**
- `postgres-chainlit-data` - PostgreSQL database (Chainlit state)
- `chainlit-uploads` - User-uploaded files
- `chainlit-logs` - Application logs
- `model_cache` - HuggingFace model cache

**External (must create beforehand):**
- `knowledge_graph_rag_neo4j_data` - Neo4j graph data
- `knowledge_graph_rag_neo4j_logs` - Neo4j logs
- `knowledge_graph_rag_neo4j_import` - Neo4j import directory
- `knowledge_graph_rag_neo4j_plugins` - Neo4j plugins

### Backup PostgreSQL

```bash
# Backup
docker exec postgres-chainlit pg_dump -U chainlit chainlit > backup.sql

# Restore
cat backup.sql | docker exec -i postgres-chainlit psql -U chainlit chainlit
```

### Reset Database

```bash
# Stop services
docker compose down

# Remove volume
docker volume rm psi-agent_postgres-chainlit-data

# Restart
docker compose up -d
```

## Development Workflow

### Hot Reload

The Chainlit app has hot reload enabled. Changes to `/app` files will automatically reload the app.

```bash
# Edit files in ./app/
vim app/app_v3_langgraph.py

# Changes auto-reload in container
```

### Debugging

```bash
# Enter container
docker exec -it psi-chainlit-app /bin/bash

# Check Python environment
docker exec psi-chainlit-app python --version
docker exec psi-chainlit-app pip list

# Test database connection
docker exec psi-chainlit-app python -c "import psycopg2; print('PostgreSQL OK')"
```

## Troubleshooting

### Chainlit App Won't Start

**Check logs:**
```bash
docker logs psi-chainlit-app --tail 50
```

**Common issues:**
- Ollama not running on host: `curl http://localhost:11434/api/tags`
- Database not ready: `docker logs postgres-chainlit`
- Missing environment variables: Check `.env` file

### MCP Servers Unhealthy

```bash
# Check individual server
curl http://localhost:8001/healthz  # AccWiki
curl http://localhost:8002/healthz  # ELOG
curl http://localhost:8003/healthz  # WebSearch

# Check logs
docker logs mcp-server-accwiki --tail 30
```

### PostgreSQL Connection Issues

```bash
# Check if PostgreSQL is running
docker exec postgres-chainlit pg_isready -U chainlit

# Connect to PostgreSQL
docker exec -it postgres-chainlit psql -U chainlit

# List databases
docker exec postgres-chainlit psql -U chainlit -c "\l"
```

### Port Conflicts

If ports are already in use:

```bash
# Find process using port
sudo lsof -i :8000

# Stop conflicting service or change port in docker-compose.yml
```

## Production Deployment

### Security Checklist

- [ ] Change `CHAINLIT_AUTH_SECRET` to a strong random value
- [ ] Set secure `CHAINLIT_ADMIN_PASSWORD`
- [ ] Change `POSTGRES_PASSWORD`
- [ ] Remove `version` from docker-compose.yml (it's obsolete)
- [ ] Use secrets management (e.g., Docker Secrets, Vault)
- [ ] Enable HTTPS/TLS
- [ ] Restrict PostgreSQL port to localhost only (already configured)
- [ ] Set up firewall rules
- [ ] Configure backup automation

### Resource Limits

Add resource limits to docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 4G
    reservations:
      cpus: '1'
      memory: 2G
```

### Health Monitoring

Set up monitoring for:
- Container health: `docker ps --format "table {{.Names}}\t{{.Status}}"`
- Disk space: PostgreSQL and logs can grow
- Memory usage: Especially for AccWiki with embeddings
- Response times: Monitor MCP tool latency

## Network Configuration

The stack uses a dedicated `psi-network` bridge network. All services can communicate using service names:

```python
# From Chainlit app
MCP_ELOG_URL = "http://mcp-server-elog:8002"
MCP_ACCWIKI_URL = "http://mcp-server-accwiki:8001"
DATABASE_URL = "postgresql://chainlit:pass@postgres-chainlit:5432/chainlit"
```

## Updating

### Pull Latest Changes

```bash
git pull
./stop-all.sh
./start-all.sh
```

### Update Dependencies

```bash
# Rebuild with --no-cache
docker compose build --no-cache chainlit-app

# Restart
docker compose up -d chainlit-app
```

## Support

For issues:
1. Check logs: `docker compose logs -f`
2. Verify health: `./start-all.sh` (shows health status)
3. Review this documentation
4. Check individual service READMEs in subdirectories
