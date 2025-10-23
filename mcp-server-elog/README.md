# ELOG MCP Server

MCP server providing intelligent search and analysis tools for SwissFEL ELOG entries using STDIO transport.

## Features

- **Direct ELOG API integration** - Always up-to-date, no database sync needed
- **Smart semantic reranking** - Cross-encoder model (ms-marco-MiniLM-L6-v2)
- **Dockerized microservice** - Easy deployment with Docker Compose
- **MCP Protocol** - STDIO transport for integration with MCP clients (Chainlit, Claude Desktop, etc.)
- **2 simplified tools**:
  1. `search_elog` - Unified search with filters, time ranges, and semantic ranking
  2. `get_elog_thread` - Thread navigation (conversation threads)

## Quick Start with Docker

```bash
# 1. Configure environment (optional)
cp .env.example .env
# Edit .env to change ELOG_URL if needed

# 2. Build and run container
docker compose up -d

# 3. Test MCP server via docker exec
docker exec -i mcp-server-elog python3 /app/server.py
```

## MCP Client Configuration

Add this to your MCP client config (e.g., `chainlit-mcp-config.json`):

```json
{
  "mcpServers": {
    "swissfel-elog": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "mcp-server-elog",
        "python3",
        "/app/server.py"
      ],
      "description": "SwissFEL ELOG - Search electronic logbook entries"
    }
  }
}
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run function tests
python test_elog_tools.py

# Run MCP server locally (STDIO)
python server.py
```

## Tool Functions (Python API)

### 1. `search_elog()`
Unified search with semantic reranking, time ranges, and filters.

```python
from logbook import Logbook
from elog_tools import search_elog

logbook = Logbook('https://elog-gfa.psi.ch/SwissFEL+test/', user='uname', password='pass')

result = search_elog(
    logbook=logbook,
    query="RF system problems",
    since="2025-10-01",
    category="Problem",
    system="RF",
    max_results=10
)

print(f"Found {result['total_found']} entries")
for hit in result['hits']:
    print(f"- [{hit['category']}] {hit['subject']}")
```

### 2. `get_elog_thread()`
Navigate message threads.

```python
from elog_tools import get_elog_thread

result = get_elog_thread(
    logbook=logbook,
    message_id=12345,
    include_replies=True,
    include_parents=True
)

print(f"Thread has {result['total_messages']} messages")
```

## Reranker

The reranker uses `cross-encoder/ms-marco-MiniLM-L6-v2` for semantic relevance scoring.

**Features:**
- Semantic similarity scoring
- Time decay (boost recent entries)
- Diversity constraints (max per category)

**Configuration:**
```python
from elog_reranker import ElogReranker, RerankConfig

config = RerankConfig(
    model_name="cross-encoder/ms-marco-MiniLM-L6-v2",
    target_k=10,
    time_decay_hours=48.0,
    max_per_category=5
)

reranker = ElogReranker(config)
reranked = reranker.rerank(hits, query)
```

## ELOG Attributes

Based on the screenshots provided, the SwissFEL ELOG has these attributes:

**Categories:**
- Info, Problem, Pikett, Access
- Measurement summary, Shift summary, Schicht-Übergabe
- Tipps & Tricks, Überbrückung, Schicht-Auftrag
- RC exchange minutes, DCM minutes
- Laser- & Gun-Performance Routine
- Weekly reference settings
- Seed laser operation

**Systems:**
- Beamdynamics, Controls, Diagnostics
- Electric supply, Feedbacks, Insertion-devices
- Laser, Magnet Power Supplies, Operation
- Photonics, PLC, RF, Safety
- Timing & Sync, Vacuum
- Water cooling & Ventilation
- Other, Unknown

**Domains:**
- Injector, Linac1, Linac2, Linac3
- Aramis, Aramis Beamlines
- Athos, Athos Beamlines
- Global

## Architecture

```
User Query
    ↓
ELOG API search (keyword matching)
    ↓
Parallel bulk read (ThreadPoolExecutor)
    ↓
Smart reranking (cross-encoder)
    ↓
Results (top-k)
```

**Why not ElasticSearch?**
- ELOG is updated daily - direct API always fresh
- No sync lag or reindexing needed
- Simpler infrastructure
- Smart reranking provides relevance scoring

## Performance

**Typical timings:**
- ELOG search (50 IDs): ~0.5s
- Parallel bulk read (50 entries): ~2-3s
- Smart reranking (50→10): ~1-2s
- **Total: ~4-6s**

**Optimizations:**
- Parallel reading with ThreadPoolExecutor (10 workers)
- Lazy model loading (only when reranking enabled)
- Batch processing for cross-encoder scoring

## Docker Management

```bash
# Build image
docker-compose build

# Start service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop service
docker-compose down

# Rebuild after code changes
docker-compose up -d --build
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ELOG_URL` | ELOG server URL | `https://elog-gfa.psi.ch/SwissFEL+test/` |
| `ELOG_USER` | ELOG username | `uname` |
| `ELOG_PASSWORD` | ELOG password | `pass` |
| `PORT` | Server port | `8000` |
