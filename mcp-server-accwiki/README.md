# PSI Accelerator Knowledge Graph - MCP Server

A Model Context Protocol (MCP) server that provides LLMs with access to the PSI accelerator facilities knowledge graph.

## Features

The MCP server exposes three tools:

### 1. `search_accelerator_knowledge`
Semantic search across the entire knowledge graph with configurable retrieval methods.

**Parameters:**
- `query` (required): Search query
- `accelerator` (optional): Filter by accelerator (hipa, proscan, sls, swissfel)
- `retriever` (optional): "dense", "sparse", or "both" (default: "both")
- `rerank` (optional): Apply cross-encoder reranking (default: false)
- `limit` (optional): Max results (default: 5, max: 20)

### 2. `hierarchical_search`
Search within a specific hierarchical context (e.g., a subsystem or component).

**Parameters:**
- `query` (required): Search query
- `context_path` (required): Hierarchical path (e.g., "hipa:p-kanal")
- `include_children` (optional): Include child nodes (default: true)
- `retriever` (optional): Retrieval method (default: "both")
- `rerank` (optional): Apply reranking (default: false)
- `limit` (optional): Max results (default: 10, max: 20)

### 3. `get_related_content`
Retrieve related articles and explore relationships in the knowledge graph.

**Parameters:**
- `article_id` (required): Article identifier
- `relationship_types` (optional): Specific relationship types to follow
- `max_depth` (optional): Traversal depth (default: 2, max: 5)

## Quick Start with Docker

### 1. Setup

```bash
cd /home/linus/psirag/AccWikiGraphRAG/mcp-server

# Copy environment variables (optional, defaults work)
cp .env.example .env

# Start the MCP server and Neo4j
docker-compose up -d
```

### 2. Check Status

```bash
# View logs
docker-compose logs -f psi-mcp-server

# Check health
docker-compose ps
```

### 3. Stop

```bash
docker-compose down
```

## Installation (Non-Docker)

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure Neo4j is running and the knowledge graph is populated.

3. Set environment variables:
```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASS=your_password
```

## Usage

### With Docker Compose

The server runs automatically when you start the containers. It connects to the Neo4j instance and is ready to accept MCP requests via stdio.

### With Claude Desktop

Add to your Claude Desktop MCP configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "psi-accelerator-knowledge": {
      "command": "python3",
      "args": [
        "/home/linus/psirag/AccWikiGraphRAG/mcp_server.py"
      ],
      "env": {
        "PYTHONPATH": "/home/linus/psirag/AccWikiGraphRAG"
      }
    }
  }
}
```

### Standalone Testing

Test the MCP server directly:

```bash
cd /home/linus/psirag/AccWikiGraphRAG
python3 mcp_server.py
```

## Example Tool Calls

### Search for information
```json
{
  "name": "search_accelerator_knowledge",
  "arguments": {
    "query": "proton beam steering magnets",
    "accelerator": "hipa",
    "retriever": "both",
    "rerank": true,
    "limit": 5
  }
}
```

### Search within a context
```json
{
  "name": "hierarchical_search",
  "arguments": {
    "query": "vacuum system specifications",
    "context_path": "hipa:p-kanal",
    "include_children": true,
    "limit": 10
  }
}
```

### Get related content
```json
{
  "name": "get_related_content",
  "arguments": {
    "article_id": "hipa:p-kanal:magnets:q1",
    "max_depth": 2
  }
}
```

## Architecture

- **Protocol**: Model Context Protocol (MCP) via stdio
- **Knowledge Graph**: Neo4j-based graph database with semantic embeddings
- **Retrieval**: Dense (vector), sparse (fulltext), and hybrid search
- **Reranking**: Optional cross-encoder reranking for improved relevance

## Comparison with REST API

The original `api_server.py` provides a REST API, while `mcp_server.py` implements the MCP protocol for direct LLM integration.

| Feature | REST API | MCP Server |
|---------|----------|------------|
| Protocol | HTTP/REST | MCP (stdio) |
| Use Case | Web integration | LLM tool integration |
| Auth | HTTP-based | Session-based |
| Discovery | OpenAPI docs | MCP tool listing |
| Client | Any HTTP client | MCP-compatible LLMs |

Both servers can run simultaneously on different ports/protocols.
