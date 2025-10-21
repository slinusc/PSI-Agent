# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Chainlit-based RAG assistant for the PSI (Paul Scherrer Institute) Accelerator Knowledge Graph. It provides three main applications:

1. **mcp_agent_router.py** (NEW, **RECOMMENDED**) - Intelligent router-based agent with hybrid workflows for AccWiki + ELOG
2. **mcp_agent_advanced.py** (645 lines) - Specialized LangGraph-based agent with self-reflection (AccWiki only)
3. **app.py** (1596 lines) - Full-featured multimodal chat assistant with authentication, file uploads, PDF processing

All applications connect to two MCP servers:
- **AccWiki** (port 8001): PSI Accelerator Knowledge Graph (HIPA, ProScan, SLS, SwissFEL)
- **ELOG** (port 8002): SwissFEL electronic logbook

## Common Commands

### Running the Applications

```bash
# Activate virtual environment
source /home/linus/.venvs/psi.venv/bin/activate

# Run the router agent (RECOMMENDED - supports AccWiki + ELOG)
cd /home/linus/psirag/chainlit
./run_router.sh
# or manually:
chainlit run mcp_agent_router.py -w --port 8000

# Run the advanced AccWiki-only agent
./run_advanced.sh

# Run the full app with authentication and file uploads
chainlit run app.py -w --port 8000
```

### Prerequisites

**Start both MCP servers** (required):
```bash
# AccWiki server (port 8001)
cd /home/linus/psirag/mcp-server-accwiki
# Start command varies - check for docker-compose.yml or run script

# ELOG server (port 8002)
cd /home/linus/psirag/mcp-server-elog
# Start command varies - check for docker-compose.yml or run script
```

**Verify MCP servers are running:**
```bash
curl http://localhost:8001/sse  # AccWiki
curl http://localhost:8002/sse  # ELOG
```

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Test PDF extraction
python test_pdf_extraction.py
```

## Architecture

### MCP Agent Router (mcp_agent_router.py) - **RECOMMENDED**

**Hybrid approach with intelligent routing** - combines flexible tool selection with structured workflows.

#### Design Philosophy
- **No forced tool use**: Router decides if tools are needed
- **Structured workflows**: When tools are used, execution is controlled and visible
- **Multiple MCPs**: Supports both AccWiki and ELOG with separate workflows
- **Self-reflection**: Evaluates quality and retries if needed

#### Workflow Graph

```
User Query
    ↓
[Router Node] - Decides route via Ollama
    ├→ general_knowledge: Answer without tools
    ├→ accwiki_search: Use AccWiki structured workflow
    ├→ elog_search: Use ELOG structured workflow
    └→ needs_clarification: Ask user for details

AccWiki Workflow:
  parse → search → evaluate → [retry or fetch_related] → generate

ELOG Workflow:
  parse → search → fetch_threads → generate
```

#### Router Decision Process

The router analyzes queries using Ollama and routes to:
1. **general_knowledge**: "What is a synchrotron?" → No tools, direct answer
2. **accwiki_search**: "HIPA buncher settings" → AccWiki knowledge graph
3. **elog_search**: "beam dump events last week" → SwissFEL ELOG
4. **needs_clarification**: "beam current issues" → Ask which facility

#### AccWiki Workflow Details
- **parse**: Extract facility (hipa/proscan/sls/swissfel), clean query
- **search**: Call `search_accelerator_knowledge` MCP tool
- **evaluate**: Ollama assesses result quality, suggests refined query if poor
- **retry loop**: Up to 3 iterations with refined queries
- **fetch_related**: Call `get_related_content` for high-score results
- **generate**: Create answer with sources and images

#### ELOG Workflow Details
- **parse**: Extract filters (category, system, domain, date ranges)
- **search**: Call `search_elog` MCP tool with filters
- **fetch_threads**: Get full conversation threads for top entries
- **generate**: Summarize findings from ELOG entries

**Key features:**
- Router uses Ollama for intelligent decision-making
- Each workflow step is a collapsible UI element in Chainlit
- Supports conversation clarification via `cl.AskUserMessage`
- Language detection (German/English) for responses

### MCP Agent Advanced (mcp_agent_advanced.py)

**AccWiki-only agent** with self-reflection. Uses **LangGraph** to orchestrate a multi-step workflow:

```
User Query
    ↓
[parse_query] - Extract facility (hipa/proscan/sls/swissfel), check if clarification needed
    ↓
[search_knowledge] - Call MCP tool search_accelerator_knowledge
    ↓
[evaluate_results] - Use Ollama to assess quality, decide if retry needed
    ↓ (if poor results and iterations < 5)
[refine_query] - Generate better query with German technical terms
    ↓ (loop back to search_knowledge)
    ↓
[get_related_content] - Fetch additional context using article_ids
    ↓
[format_answer] - Generate final answer with Ollama
```

**Key features:**
- Self-reflection: evaluates search results and retries up to 5 times
- Uses `get_related_content` MCP tool when article IDs are found
- Each step is a collapsible UI element in Chainlit
- Ollama model `PSI_Assistant:latest` for answer generation

### Full App (app.py)

Feature-rich Chainlit application with:

- **SQLiteDataLayer**: Custom data persistence (threads, steps, users, feedback) in `chainlit.db`
- **Authentication**: Basic auth using credentials from `.env`
- **File uploads**: Supports text files, PDFs (via `pdf_processor.py`), and images
- **Multimodal**: Vision models (qwen2.5vl:32b) can analyze images
- **MCP integration**: Calls both accwiki and e-log MCP servers
- **Settings UI**: Model selection, temperature, system prompt customization
- **Chat history**: Persists conversations with configurable message limit

**State management:**
- `ChatSessionState` dataclass stores messages, context_files, and settings per session
- Context files are tracked and shown in UI as attachments
- Settings are stored in database and can be changed via chat settings panel

### PDF Processing (pdf_processor.py)

Modular PDF text extraction supporting PyMuPDF (primary) or pdfplumber (fallback):
- `extract_pdf_text()` - Main extraction function
- `extract_pdf_text_safe()` - Wrapper that returns error message instead of raising exceptions

## Configuration

### Environment Variables (.env)

```bash
OLLAMA_HOST=http://localhost:11434
MCP_SERVER_URL=http://localhost:8001       # accwiki server
DEFAULT_MODEL=qwen2.5vl:32b
CHAINLIT_AUTH_SECRET=<secret>
CHAINLIT_ADMIN_USERNAME=admin@chainlit.com
CHAINLIT_ADMIN_PASSWORD=<password>
```

### Chainlit Config (.chainlit/config.toml)

- Authentication: `auth.mode = "basic"`
- MCP enabled: `features.mcp.enabled = true`
- Two MCP servers configured:
  - `e-log` on port 8002
  - `accwiki` on port 8001
- File uploads: max 20 files, 500MB limit
- LaTeX rendering enabled

### Model Configuration

Models configurable via `OLLAMA_MODELS` env var (comma-separated). Default: `qwen2.5vl:32b`

Chat history limit: `CHAT_HISTORY_LIMIT` (default: 40 messages)

## MCP Tool Usage

### Available MCP Tools

#### AccWiki MCP (port 8001)

**search_accelerator_knowledge**
```python
{
    "query": str,              # Search query (German or English)
    "accelerator": str,        # "hipa"|"proscan"|"sls"|"swissfel"|"all"
    "retriever": str,          # "dense"|"sparse"|"hybrid" (default: "dense")
    "limit": int              # Number of results (default: 5)
}
```

**get_related_content**
```python
{
    "article_id": str,         # Article ID from search results
    "max_depth": int          # How many levels of relations to fetch (default: 2)
}
```

#### ELOG MCP (port 8002)

**search_elog**
```python
{
    "query": str,              # Search text or regex (optional if using filters)
    "since": str,              # Start date YYYY-MM-DD (optional)
    "until": str,              # End date YYYY-MM-DD (optional)
    "category": str,           # Shift|Problem|Info|Solution|Routine|Configuration
    "system": str,             # RF|Timing|Vacuum|Diagnostics|Laser|Magnets|Controls|...
    "domain": str,             # Aramis|Athos|Alvra|Bernina|Cristallina|Maloja|...
    "limit": int              # Number of results (default: 10)
}
```

**get_elog_thread**
```python
{
    "entry_id": int           # ELOG entry ID to fetch conversation thread
}
```

### Facility Keyword Detection

The advanced agent automatically detects facility names:
- **hipa**: "hipa", "hochleistungs"
- **proscan**: "proscan", "gantry"
- **sls**: "sls", "swiss light source", "synchrotron"
- **swissfel**: "swissfel", "swiss-fel", "xfel", "aramis", "athos", "ctf3"

## Key Implementation Patterns

### Creating Chainlit Steps (for LangGraph nodes)

```python
async def my_node(state: AgentState) -> AgentState:
    async with cl.Step(name="🔍 Step Name", type="tool") as step:
        # Do work
        step.output = "What to show in UI"
        step.elements = [cl.Text(name="Details", content="...")]
        return {**state, "key": value}
```

Step types: `"tool"` (green) or `"llm"` (blue)

### MCP Connection Pattern

```python
from mcp.client.sse import sse_client
from mcp import ClientSession

async with sse_client(MCP_SERVER_URL + "/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("tool_name", params)
        data = json.loads(result.content[0].text)
```

### Ollama Streaming in Chainlit

```python
async with cl.Step(name="Answer", type="llm") as step:
    msg = cl.Message(content="")
    async for chunk in client.chat(model=model, messages=messages, stream=True):
        await msg.stream_token(chunk['message']['content'])
    await msg.send()
```

## File Locations

- **Uploads**: `data/uploads/` (configurable via `CHAINLIT_UPLOAD_DIR`)
- **Logs**: `logs/chainlit_app.log` (configurable via `CHAINLIT_LOG_DIR`)
- **Database**: `chainlit.db` (SQLite, configurable via `CHAINLIT_DB_PATH`)
- **Static files**: `public/` (served at `/public/`)
- **Custom JS**: `public/custom.js` (loaded via config.toml)

## Testing

```bash
# Test PDF extraction
python test_pdf_extraction.py

# Check if MCP server responds
curl http://localhost:8001/sse

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

## Common Issues

**MCP connection errors**: Verify both MCP servers are running in docker compose

**Ollama errors**: Check model exists: `ollama list` and ensure `PSI_Assistant:latest` is available for advanced agent

**Authentication**: Default admin credentials are in `.env` file

**File upload limits**: Check `max_size_mb` in `.chainlit/config.toml` (default: 500MB)
