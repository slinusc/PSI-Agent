# PSI RAG Assistant - Complete Documentation

**Autonomous Agent System with Guided Autonomy**

Version: 2.0
Last Updated: 2025-10-10

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Getting Started](#getting-started)
4. [Guided Autonomy System](#guided-autonomy-system)
5. [System Prompt Configuration](#system-prompt-configuration)
6. [Intelligent Fallback System](#intelligent-fallback-system)
7. [MCP Tool Integration](#mcp-tool-integration)
8. [Usage Examples](#usage-examples)
9. [Configuration](#configuration)
10. [Testing](#testing)
11. [Troubleshooting](#troubleshooting)
12. [Development](#development)

---

## Overview

The PSI RAG Assistant is an autonomous agent system that provides intelligent access to PSI accelerator documentation and operational logs through MCP (Model Context Protocol) tools.

### Key Features

✅ **Guided Autonomy**: Agent dynamically plans tool usage with built-in guardrails
✅ **Multi-Tool Queries**: Can combine AccWiki + ELOG for comprehensive answers
✅ **Intelligent Fallbacks**: 3-iteration refinement with user choice on failure
✅ **Self-Correction**: Evaluates results and replans if insufficient
✅ **Transparent**: Shows planning, execution, and evaluation steps
✅ **Customizable**: User-editable system prompt with dynamic tool listing

### Files Overview

```
chainlit/
├── app.py                    # Original router-based system
├── app_v2.py                 # NEW: Autonomous agent system
├── autonomous_agent.py       # Core autonomous agent logic
├── router_agent.py           # Legacy router (used as fallback)
├── pdf_processor.py          # PDF text extraction
└── README.md                 # This file
```

---

## Architecture

### System Design

```
User Query
    ↓
┌─────────────────────────────────────────────┐
│  Chainlit App (app_v2.py)                   │
│  - Session management                       │
│  - MCP connection handling                  │
│  - Settings UI                              │
└─────────────┬───────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│  Autonomous Agent (autonomous_agent.py)     │
│  ┌─────────────────────────────────────┐   │
│  │  1. Planning Phase                  │   │
│  │     - Analyze query + available tools│   │
│  │     - Generate execution plan (JSON)│   │
│  │     - Include evaluation steps      │   │
│  └─────────────┬───────────────────────┘   │
│                ↓                            │
│  ┌─────────────────────────────────────┐   │
│  │  2. Execution Phase (3 iterations)  │   │
│  │     - Execute tool calls            │   │
│  │     - Evaluate result quality       │   │
│  │     - Refine if poor                │   │
│  └─────────────┬───────────────────────┘   │
│                ↓                            │
│  ┌─────────────────────────────────────┐   │
│  │  3. Synthesis Phase                 │   │
│  │     - Combine all results           │   │
│  │     - Generate answer with citations│   │
│  └─────────────────────────────────────┘   │
└─────────────┬───────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│  MCP Tools                                  │
│  - search_accelerator_knowledge (AccWiki)   │
│  - search_elog (SwissFEL ELOG)             │
│  - get_related_content                      │
│  - get_elog_thread                          │
└─────────────────────────────────────────────┘
```

### Key Components

#### 1. Autonomous Agent (`autonomous_agent.py`)

**Core autonomous reasoning engine with:**
- **Planning**: LLM-based plan generation with tool selection
- **Execution**: Tool calling with policy enforcement
- **Evaluation**: Result quality assessment with refinement suggestions
- **Synthesis**: Answer generation with source citations

**Key Classes:**
- `AutonomousAgent`: Main agent class
- `ToolUsagePolicy`: Rate limits and duplicate detection
- `Plan/PlanStep`: Structured execution plans
- `ExecutionResult`: Tool call results

#### 2. Application (`app_v2.py`)

**Chainlit web interface with:**
- Session management (chat history, context files)
- MCP connection handling
- User authentication
- Settings UI (model, temperature, system prompt, tool toggle)
- PDF upload and processing

#### 3. MCP Integration

**Supported MCP Servers:**
- **accwiki**: PSI accelerator knowledge graph
  - `search_accelerator_knowledge`: Search technical documentation
  - `get_related_content`: Retrieve related articles
- **elog**: SwissFEL electronic logbook
  - `search_elog`: Search operational logs with filters
  - `get_elog_thread`: Get conversation threads

---

## Getting Started

### Prerequisites

```bash
# Python 3.10+
python --version

# Install dependencies
cd /home/linus/psirag/chainlit
pip install -r requirements.txt

# Ollama running locally
ollama serve
```

### Configuration

1. **Configure MCP servers** in `.chainlit/config.toml`:

```toml
[[mcps]]
name = "accwiki"
command = "python"
args = ["-m", "mcp_accwiki.server"]

[[mcps]]
name = "elog"
command = "python"
args = ["-m", "mcp_elog.server"]
```

2. **Set environment variables** in `.env`:

```bash
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=llama3.3:70b
```

### Running the Application

```bash
# Start the autonomous agent system
chainlit run app_v2.py

# Or start the legacy router system
chainlit run app.py
```

Access at: `http://localhost:8000`

---

## Guided Autonomy System

### What is Guided Autonomy?

The agent has **freedom** to choose tools and plan workflows, but is **guided** through:

1. **System prompts** describing tool purposes and usage
2. **JSON schemas** enforcing parameter validation
3. **Usage policies** preventing abuse (rate limits, duplicates)
4. **Evaluation criteria** for quality assessment

### How It Works

#### Planning Phase

The agent creates a structured plan:

```json
{
  "strategy": "multi_tool",
  "confidence": 0.90,
  "reasoning": "Query needs both documentation and operational context",
  "steps": [
    {
      "step_id": 1,
      "action": "tool_call",
      "tool_calls": [{
        "tool_name": "search_accelerator_knowledge",
        "arguments": {"query": "...", "accelerator": "sls"},
        "reasoning": "Get technical documentation"
      }]
    },
    {
      "step_id": 2,
      "action": "evaluate",
      "evaluation_criteria": "Check if results answer the question"
    },
    {
      "step_id": 3,
      "action": "tool_call",
      "tool_calls": [{
        "tool_name": "search_elog",
        "arguments": {"query": "...", "system": "Beamdynamics"},
        "reasoning": "Get operational logs"
      }]
    },
    {
      "step_id": 4,
      "action": "synthesize"
    }
  ]
}
```

**Key Innovation**: Evaluation is part of the plan, not hardcoded!

#### Execution Phase

```python
for iteration in range(max_iterations):  # max_iterations = 3
    for step in plan.steps:
        if step.action == "tool_call":
            execute_tools()
        elif step.action == "evaluate":
            quality = evaluate_results()
            if quality == "poor":
                continue  # Try next steps (fallbacks)
        elif step.action == "synthesize":
            generate_answer()
            break

    # After all steps, evaluate overall quality
    if results_insufficient and iteration < max_iterations:
        refined_plan = replan_with_feedback()
    else:
        break
```

#### Synthesis Phase

Combines all gathered information:

```python
# Build context from tool results
context = []
for result in execution_context:
    if result.tool == "search_accelerator_knowledge":
        context.append(f"[AccWiki] {result.data}")
    elif result.tool == "search_elog":
        context.append(f"[ELOG] {result.data}")

# Generate answer with citations
answer = llm.generate(
    system_prompt=user_system_prompt,
    context=context,
    query=user_query,
    instructions="Cite sources as [Source X] or [ELOG Entry Y]"
)
```

### Tool Usage Policies

**Guardrails prevent abuse:**

```python
class ToolUsagePolicy:
    max_calls_per_tool = 3      # Max 3 calls to same tool
    max_total_calls = 8          # Max 8 total calls per query

    def can_call_tool(tool_name, arguments):
        # Check rate limits
        if tool_call_count[tool_name] >= 3:
            return False, "Max calls per tool exceeded"

        # Detect duplicates
        if (tool_name, arguments) in call_history:
            return False, "Duplicate call detected"

        return True, ""
```

### Comparison: Old vs New

| Feature | app.py (Router) | app_v2.py (Autonomous) |
|---------|-----------------|------------------------|
| **Tool Selection** | Pre-decided route | Dynamic planning |
| **Multi-tool** | ❌ Cannot combine | ✅ Can use multiple tools |
| **Self-Correction** | ❌ No retry | ✅ 3-iteration refinement |
| **Evaluation** | Hardcoded loop | Part of the plan |
| **Transparency** | Hidden | ✅ Shows all steps |
| **Flexibility** | Fixed workflows | ✅ Agent-designed workflows |
| **Guardrails** | None | ✅ Rate limits, duplicates |

---

## System Prompt Configuration

### Dynamic System Prompt

The system prompt is built dynamically with available MCP tools:

**Base Template** (`DEFAULT_SYSTEM_PROMPT` in app_v2.py):

```python
DEFAULT_SYSTEM_PROMPT = """You are the PSI assistant. Provide concise, factual answers.

You have access to MCP tools for accessing internal information sources:
{mcp_tools_list}

When tool information, documents, or images are supplied, ground your answers in that material and cite sources clearly.

If you call tools, explain the results in plain language.

If information is missing, ask clarifying questions before assuming.

You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$
[expression]
$$' for standalone cases."""
```

**Dynamic Tool List**:

```python
def build_system_prompt_with_tools(base_prompt, mcp_tools):
    """Replace {mcp_tools_list} with actual tools"""

    tool_lines = []
    for mcp_name, tools in mcp_tools.items():
        for tool in tools:
            tool_name = tool["name"]
            tool_desc = tool["description"][:150]  # Truncate
            tool_lines.append(f"- {tool_name}: {tool_desc}")

    tools_text = "\n".join(tool_lines)
    return base_prompt.replace("{mcp_tools_list}", tools_text)
```

**Result**:

```
You are the PSI assistant. Provide concise, factual answers.

You have access to MCP tools for accessing internal information sources:
- search_accelerator_knowledge: Search the PSI accelerator knowledge graph for technical information...
- get_related_content: Retrieve related content and context for a specific article...
- search_elog: Search SwissFEL ELOG entries with semantic ranking...
- get_elog_thread: Get full conversation thread for an ELOG entry...

When tool information, documents, or images are supplied, ground your answers in that material and cite sources clearly.
...
```

### User Customization

Users can edit the system prompt via **Settings (⚙️)**:

1. Click settings icon
2. Edit "System Prompt" field
3. Save → Agent updated immediately
4. New MCP tools auto-appear in {mcp_tools_list}

**Example Customization**:

```
You are a SwissFEL operations specialist. Always prioritize ELOG over AccWiki.

You have access to MCP tools:
{mcp_tools_list}

When answering:
- Include exact timestamps from ELOG
- Reference equipment IDs
- Be extremely detailed
...
```

### Integration Points

1. **Chat Start**: System prompt built with current MCP tools
2. **Settings Update**: Prompt rebuilt when user changes it
3. **Planning**: Prepended to planning prompt
4. **Answer Synthesis**: Prepended to answer prompt

---

## Intelligent Fallback System

### 3-Iteration Refinement

When results are insufficient, the agent:

1. **Evaluates** what went wrong
2. **Refines** the search strategy
3. **Retries** up to 3 times
4. **Asks user** for guidance if still failing

### Workflow

```
┌─────────────────────────────────────┐
│  Iteration 1: Initial Search        │
│  - Execute planned tool calls       │
│  - Evaluate: Good or Poor?          │
└─────────────┬───────────────────────┘
              ↓
         Good Results?
         /          \
       YES          NO
        ↓            ↓
    Synthesize  ┌───────────────────────────┐
    Answer      │ Iteration 2: Refined      │
                │ - LLM suggests refinement │
                │ - "Try German terms"      │
                │ - "Add facility filter"   │
                │ - Re-execute search       │
                └─────────┬─────────────────┘
                          ↓
                     Good Results?
                     /          \
                   YES          NO
                    ↓            ↓
                Synthesize  ┌──────────────────────┐
                Answer      │ Iteration 3: Final   │
                            │ - Last refinement    │
                            │ - Multi-tool attempt │
                            └──────┬───────────────┘
                                   ↓
                              Good Results?
                              /          \
                            YES          NO
                             ↓            ↓
                         Synthesize   Ask User
                         Answer       What to Do
```

### Refinement Strategies

The evaluation LLM suggests specific refinements:

**Strategy 1: Language Translation**
```
Problem: English query on German docs
Refinement: "Try German term: Skew Quadrupol Strahlgröße"
```

**Strategy 2: Tool Switch**
```
Problem: Using AccWiki for operational questions
Refinement: "Use ELOG instead - this is operational"
```

**Strategy 3: Add Filters**
```
Problem: Generic search, too many results
Refinement: "Add accelerator='sls' filter"
```

**Strategy 4: Different Retriever**
```
Problem: Keyword search missing semantic matches
Refinement: "Use retriever='dense' for semantic search"
```

**Strategy 5: Multi-Tool**
```
Problem: Single tool insufficient
Refinement: "Combine AccWiki (docs) + ELOG (logs)"
```

### User Choice on Failure

After 3 failed attempts:

```
After multiple attempts, I couldn't find sufficient information.

**What was tried:**
- Tools used: search_accelerator_knowledge, search_elog
- Evaluation: No operational logs found, AccWiki results insufficient

**How would you like to proceed?**

1. **More specific search**: Could you provide more details?
   - Specific time period?
   - Particular component or system?
   - Which tool should I use? (AccWiki for documentation, ELOG for operational logs)

2. **General answer**: Should I answer based on my general knowledge (without specific PSI data)?

Please provide more details or tell me how to proceed.
```

**User can respond:**
- "Search AccWiki for 'Strahllebensdauer' in SLS Betrieb section"
- "Just give me a general answer"
- "Try ELOG with time range 2024-01-01 to now"

---

## MCP Tool Integration

### Available Tools

#### 1. search_accelerator_knowledge (AccWiki)

**Purpose**: Search PSI accelerator knowledge graph

**Parameters**:
```python
{
  "query": str,           # Search query (German recommended)
  "accelerator": str,     # "hipa"|"proscan"|"sls"|"swissfel"|"all"
  "retriever": str,       # "dense"|"sparse"|"both"
  "limit": int            # Max results (1-20)
}
```

**Example**:
```python
result = await search_accelerator_knowledge(
    query="Buncher Funktionsweise",
    accelerator="hipa",
    retriever="dense",
    limit=5
)
```

**Returns**:
```json
{
  "results": [
    {
      "article_id": "12345",
      "title": "HIPA Buncher System",
      "content": "Der Buncher ist...",
      "score": 0.89,
      "url": "https://accwiki.psi.ch/article/12345",
      "images": [...]
    }
  ]
}
```

#### 2. search_elog (ELOG)

**Purpose**: Search SwissFEL electronic logbook

**Parameters**:
```python
{
  "query": str,          # Search text or regex pattern
  "since": str,          # Date (YYYY-MM-DD)
  "until": str,          # Date (YYYY-MM-DD)
  "category": str,       # "Problem"|"Info"|"Shift summary"|...
  "system": str,         # "RF"|"Vacuum"|"Diagnostics"|...
  "domain": str,         # "Aramis"|"Athos"|"Global"|...
  "max_results": int     # Max entries (1-50)
}
```

**Example**:
```python
result = await search_elog(
    query="beam.*dump",
    since="2024-10-01",
    system="Beamdynamics",
    max_results=10
)
```

**Returns**:
```json
{
  "ok": true,
  "results": {
    "hits": [
      {
        "elog_id": 98765,
        "timestamp": "Thu, 03 Oct 2024 14:23:17 +0200",
        "title": "Beam dump event",
        "author": "John Doe",
        "body_clean": "Beam was dumped due to...",
        "category": "Problem",
        "system": "Beamdynamics",
        "url": "https://elog.psi.ch/..."
      }
    ]
  }
}
```

#### 3. get_related_content

**Purpose**: Get related articles from AccWiki

**Parameters**:
```python
{
  "article_id": str,           # Article ID
  "relationship_types": list,  # Optional
  "max_depth": int            # Traversal depth (1-5)
}
```

#### 4. get_elog_thread

**Purpose**: Get full conversation thread from ELOG

**Parameters**:
```python
{
  "message_id": int,           # ELOG entry ID
  "include_replies": bool,     # Include descendants
  "include_parents": bool      # Include ancestors
}
```

### Adding New MCP Tools

1. **Configure** in `.chainlit/config.toml`:
```toml
[[mcps]]
name = "new_tool"
command = "python"
args = ["-m", "mcp_new_tool.server"]
```

2. **Restart** Chainlit → Tool auto-appears in system prompt

3. **No code changes needed!**

---

## Usage Examples

### Example 1: Simple Documentation Query

**User**: "How does the SLS storage ring work?"

**Agent Plan**:
```json
{
  "strategy": "direct_search",
  "steps": [
    {"action": "tool_call", "tool": "search_accelerator_knowledge",
     "args": {"query": "SLS Speicherring Funktionsweise", "accelerator": "sls"}},
    {"action": "synthesize"}
  ]
}
```

**Result**: Technical explanation with AccWiki citations

---

### Example 2: Operational Query

**User**: "Any beam dumps yesterday?"

**Agent Plan**:
```json
{
  "strategy": "direct_search",
  "steps": [
    {"action": "tool_call", "tool": "search_elog",
     "args": {"query": "beam dump", "since": "2024-10-09", "category": "Problem"}},
    {"action": "synthesize"}
  ]
}
```

**Result**: List of ELOG entries with timestamps

---

### Example 3: Multi-Tool Query

**User**: "Explain the SwissFEL RF system and recent problems with it"

**Agent Plan**:
```json
{
  "strategy": "multi_tool",
  "steps": [
    {"action": "tool_call", "tool": "search_accelerator_knowledge",
     "args": {"query": "SwissFEL RF System", "accelerator": "swissfel"}},
    {"action": "evaluate"},
    {"action": "tool_call", "tool": "search_elog",
     "args": {"query": "RF.*problem", "system": "RF", "since": "2024-09-01"}},
    {"action": "evaluate"},
    {"action": "synthesize"}
  ]
}
```

**Result**: Technical background + recent operational issues

---

### Example 4: Refinement Scenario

**User**: "Skew Quadrupole magnet beam size at SLS"

**Iteration 1**:
```
Tool: search_accelerator_knowledge("Skew Quadrupole beam size", "sls")
Result: Software applications (irrelevant)
Evaluation: Poor - "Results about software, not magnet specs"
Refinement: "Try German term: Skew Quadrupol Strahlgröße"
```

**Iteration 2**:
```
Tool: search_accelerator_knowledge("Skew Quadrupol Strahlgröße", "sls", retriever="dense")
Result: General SLS info (insufficient)
Evaluation: Poor - "Mentions SLS but not specific to Skew Quadrupole"
Refinement: "Add ELOG for operational context"
```

**Iteration 3**:
```
Tool 1: search_accelerator_knowledge("Skew Quadrupol Lebensdauer", "sls")
Tool 2: search_elog("Skew Quadrupole.*lifetime", domain="Global")
Result: Still insufficient
Action: Ask user for guidance
```

---

## Configuration

### Application Settings

Edit `app_v2.py`:

```python
# Ollama configuration
OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.3:70b"

# Agent settings
max_iterations = 3  # Refinement attempts

# Policy settings (in autonomous_agent.py)
max_calls_per_tool = 3
max_total_calls = 8
```

### User Settings (via UI)

- **Model**: Select Ollama model
- **Temperature**: 0.0 (deterministic) to 1.0 (creative)
- **System Prompt**: Custom instructions
- **Use Tools**: Enable/disable MCP tool usage

### Environment Variables

Create `.env`:

```bash
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=llama3.3:70b
CHAINLIT_AUTH_SECRET=your-secret-key
```

---

## Testing

### Test Queries

**Test 1: Single Tool (AccWiki)**
```
Query: "How does the SLS storage ring work?"
Expected: Uses search_accelerator_knowledge only
```

**Test 2: Single Tool (ELOG)**
```
Query: "Beam dumps yesterday?"
Expected: Uses search_elog only
```

**Test 3: Multi-Tool**
```
Query: "SwissFEL RF system and recent problems"
Expected: Uses both AccWiki + ELOG
```

**Test 4: Refinement**
```
Query: "Skew Quadrupole magnet"
Expected: 2-3 refinement iterations with German terms
```

**Test 5: Failure Fallback**
```
Query: "Quantum multiverse fluctuations"
Expected: 3 attempts → ask user for guidance
```

### Running Tests

```bash
# Start app
chainlit run app_v2.py

# Compare with old router
chainlit run app.py -p 8001

# Test same query in both
```

---

## Troubleshooting

### Issue: MCP tools not available

**Symptoms**: "No MCP tools available" in logs

**Solutions**:
1. Check `.chainlit/config.toml` has MCP server configs
2. Verify MCP servers are accessible:
   ```bash
   python -m mcp_accwiki.server  # Test manually
   ```
3. Restart Chainlit

### Issue: Tool validation errors

**Symptoms**: "Tool validation error: 'default' is not one of..."

**Solutions**:
1. Check agent is using valid enum values
2. Review planning prompt guidance
3. Inspect tool schemas in logs

### Issue: Agent always fails after 3 attempts

**Symptoms**: Always shows "Ask user" prompt

**Solutions**:
1. Check evaluation is not too strict
2. Verify MCP tools return valid data
3. Review refinement suggestions in logs

### Issue: System prompt doesn't include tools

**Symptoms**: Prompt shows `{mcp_tools_list}` literally

**Solutions**:
1. Verify `build_system_prompt_with_tools()` is called
2. Check MCP tools are registered before agent init
3. See logs for "MCP connection established"

---

## Development

### Project Structure

```
chainlit/
├── app_v2.py                 # Main application
├── autonomous_agent.py       # Autonomous agent logic
├── router_agent.py           # Legacy workflows
├── pdf_processor.py          # PDF extraction
├── .chainlit/
│   └── config.toml          # MCP server config
├── .env                     # Environment variables
└── README.md               # This file
```

### Key Classes

**`AutonomousAgent`** (autonomous_agent.py):
- `process_query()` - Main entry point
- `_create_plan()` - LLM-based planning
- `_execute_tool()` - Tool execution with policies
- `_evaluate_results()` - Quality assessment
- `_replan()` - Refinement planning
- `_synthesize_answer()` - Answer generation
- `_ask_user_on_failure()` - User choice prompt

**`ToolUsagePolicy`** (autonomous_agent.py):
- `can_call_tool()` - Check if tool call allowed
- `record_call()` - Track call history
- `reset()` - Clear history for new query

### Adding Features

**Example: Add a new action type**

1. Update `PlanStep` dataclass:
```python
@dataclass
class PlanStep:
    action: str  # Add "your_new_action" here
```

2. Add handler in execution loop:
```python
elif step.action == "your_new_action":
    # Your logic here
    pass
```

3. Update planning prompt to describe new action

---

## Changelog

### Version 2.0 (2025-10-10)

✅ Autonomous agent with guided autonomy
✅ Evaluation as part of planning
✅ 3-iteration intelligent fallback
✅ Dynamic system prompt with MCP tools
✅ User choice on persistent failure
✅ Tool usage policies (rate limits, duplicates)

### Version 1.0

- Router-based system (app.py)
- Fixed workflows for AccWiki and ELOG
- Basic MCP integration

---

## License

Internal PSI project

---

## Contact

For questions or issues, contact the PSI RAG team.
