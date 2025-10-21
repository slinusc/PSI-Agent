# PSI Accelerator Knowledge Graph - Claude Integration Guide

This MCP server provides Claude (via Onyx or other MCP clients) with access to the PSI accelerator facilities knowledge graph.

## System Prompt for Claude

Use the content from **`ONYX_SYSTEM_PROMPT.md`** as Claude's system prompt. This ensures:
- Proper parameter extraction (facility names → `accelerator` parameter)
- Correct tool usage patterns
- Exact URL citation from results
- No hallucinated sources

## Critical Instructions for Claude

### 1. Parameter Extraction
**❌ Wrong**: Put everything in the query
```json
{"query": "HIPA buncher problems at MXZ3/4"}
```

**✅ Correct**: Extract facility to parameter
```json
{"query": "buncher problems at MXZ3/4", "accelerator": "hipa"}
```

### 2. Source Citation
**❌ Wrong**: Make up or construct URLs
```markdown
Source: https://acceleratorwiki.psi.ch/hipa/buncher_operation
```

**✅ Correct**: Use exact URLs from tool results
```markdown
Source: [Zeitstrukturmessung HIPA](https://acceleratorwiki.psi.ch/wiki/Zeitstrukturmessung_HIPA)
```

### 3. Image Inclusion
**❌ Wrong**: Skip images or make up URLs
```markdown
(no images mentioned)
```

**✅ Correct**: Include relevant images from results
```markdown
![Zeitstruktur measurement](https://acceleratorwiki.psi.ch/w/images/thumb/2/23/Zeitstruktur1100.png/300px-Zeitstruktur1100.png)
```

## Available Tools

### `search_accelerator_knowledge`
Search the knowledge graph with semantic/keyword retrieval.

**Key Parameters**:
- `query` (required): Search topic WITHOUT facility names
- `accelerator` (optional): "hipa"|"proscan"|"sls"|"swissfel"|"all"
- `retriever` (optional): "dense"|"sparse"|"both" (default: "dense")
- `limit` (optional): 1-20 results (default: 5)

**Example**:
```json
{
  "query": "Dosisleistungsmonitore Ausfall Maßnahmen",
  "accelerator": "swissfel",
  "retriever": "dense",
  "limit": 5
}
```

### `get_related_content`
Explore article relationships and related content.

**Key Parameters**:
- `article_id` (required): Article identifier from search results
- `relationship_types` (optional): Array like ["REFERENCES", "CONTAINS", "PART_OF"]
- `max_depth` (optional): 1-5 (default: 2)

**Example**:
```json
{
  "article_id": "hipa:iw2-ip2:article:superbuncher",
  "max_depth": 2
}
```

## Usage Patterns

### Pattern 1: Facility-Specific Question
```
User: "What happens if dose monitors fail at HIPA?"

Step 1 - Parse: facility="HIPA", topic="dose monitor failure procedures"
Step 2 - Tool call:
{
  "query": "Dosisleistungsmonitore Ausfall Sicherheitsmaßnahmen",
  "accelerator": "hipa"
}
Step 3 - Use exact URLs and images from results
```

### Pattern 2: Subsystem-Specific Question
```
User: "Tell me about the HIPA proton channel vacuum system"

Step 1 - Parse: facility="HIPA", subsystem="p-kanal", topic="vacuum system"
Step 2 - Tool call:
{
  "query": "vacuum system specifications",
  "context_path": "hipa:p-kanal",
  "include_children": true
}
```

### Pattern 3: General Question
```
User: "How do accelerators prevent radiation exposure?"

Step 1 - No facility mentioned → search all
Step 2 - Tool call:
{
  "query": "radiation protection safety measures",
  "accelerator": "all",
  "limit": 10
}
```

### Pattern 4: Follow-up with Related Content
```
Step 1 - Initial search returns article_id
Step 2 - Get related content:
{
  "article_id": "hipa:iw2-ip2:article:superbuncher",
  "relationship_types": ["REFERENCES", "CONTAINS"],
  "max_depth": 2
}
```

## Response Format

### Structure
```markdown
[Brief answer based on retrieved information]

[Detailed explanation using specific technical details from results]

**Sources**:
- [Article Title 1](exact_url_from_results)
- [Article Title 2](exact_url_from_results)

[Relevant images if they add value]
![Description](exact_image_url_from_results)
```

### Example
```markdown
The buncher at MXZ3/4 in HIPA experiences problems when the bunch length exceeds
the linear range of the 506MHz sine voltage. This is problematic because a buncher
should operate within the linear range of the buncher voltage.

The measurements show that the bunch length at the superbuncher location (MXZ3/4)
exceeds the linear operating region of the sine voltage, particularly at higher
beam currents.

**Sources**:
- [Zeitstrukturmessung HIPA](https://acceleratorwiki.psi.ch/wiki/Zeitstrukturmessung_HIPA)
- [Portal:Strahlentwicklung HIPA/Superbuncher](https://acceleratorwiki.psi.ch/wiki/Portal:Strahlentwicklung_HIPA/Superbuncher)

![Time structure measurement at different currents](https://acceleratorwiki.psi.ch/w/images/thumb/2/23/Zeitstruktur1100.png/300px-Zeitstruktur1100.png)
```

## Common Mistakes to Avoid

### ❌ Facility name in query
```json
{"query": "HIPA Dosisleistungsmonitore"}  // WRONG
{"query": "Dosisleistungsmonitore", "accelerator": "hipa"}  // CORRECT
```

### ❌ Constructed/guessed URLs
```markdown
Source: https://acceleratorwiki.psi.ch/hipa/buncher  // WRONG (made up)
Source: [Buncher](https://acceleratorwiki.psi.ch/wiki/Buncher)  // CORRECT (from results)
```

### ❌ Ignoring images in results
```markdown
(text only, no images)  // WRONG
![Buncher diagram](https://acceleratorwiki.psi.ch/w/images/.../Buncher_fig2.png)  // CORRECT
```

### ❌ Not trying multiple searches
```
First search returns poor results → give up  // WRONG
First search returns poor results → refine query, try different retriever, adjust parameters  // CORRECT
```

## Quality Metrics

Evaluate tool results by checking `score` values:
- **Dense retriever**: >0.7 = good, 0.5-0.7 = partial, <0.5 = poor
- **Sparse retriever**: Higher BM25 scores = better
- **Hybrid (both)**: >0.015 = good (RRF scores)

If scores are low:
1. Rephrase query (German ↔ English, synonyms)
2. Try different retriever
3. Adjust accelerator filter
4. Increase limit
5. Chain with `get_related_content`

## Troubleshooting

### Tool validation errors
- Ensure `query` parameter is always provided
- Check that `accelerator` values are valid: "hipa"|"proscan"|"sls"|"swissfel"|"all"|""
- Verify JSON syntax (no trailing commas, proper quotes)

### Poor results
- Use German queries (knowledge base is primarily German)
- Start with `retriever: "dense"` for semantic search
- Try `retriever: "both"` for hybrid approach
- Use hierarchical_search for subsystem-specific queries

### Hallucinated sources
- Double-check system prompt is loaded
- Verify tool results contain URLs
- Some models hallucinate despite instructions - try Claude 3.5 Sonnet or GPT-4

## Technical Details

- **MCP Server**: HTTP/SSE transport on port 8001
- **Knowledge Graph**: Neo4j with BGE-M3 embeddings
- **Retrieval**: Dense (cosine similarity), Sparse (BM25), Hybrid (RRF)
- **Default Retriever**: Dense (semantic vector search)
- **Languages**: Primary German, supports English queries

---

## Chainlit Implementation (Advanced Agent)

A **self-reflective LangGraph agent** has been built for better control and quality:

### Features
- ✅ **Quality evaluation**: Uses Ollama to judge if results are good enough
- ✅ **Iterative refinement**: Retries search up to 5 times if quality is poor
- ✅ **Related content**: Automatically fetches related articles via `get_related_content`
- ✅ **Language detection**: Responds in user's language (German/English)
- ✅ **Deduplicated citations**: Same article only cited once (not per chunk)
- ✅ **Ollama generation**: Natural language answers from context
- ✅ **Visible reasoning**: Each step shown in UI (collapsible)

### Workflow
```
User Query
    ↓
[Parse Query] - Extract facility & detect language
    ↓
[Search Knowledge] - Call MCP search tool
    ↓
[Evaluate Results] - Ollama judges quality
    ↓
  Good? ──No──→ Retry search (max 5x)
    │
   Yes
    ↓
[Fetch Related] - Get related articles via article_ids
    ↓
[Generate Answer] - Ollama creates answer in user's language
    ↓
Display with deduplicated sources & images
```

### Files
- **Simple version**: `/home/linus/psirag/chainlit/mcp_agent.py`
- **Advanced version**: `/home/linus/psirag/chainlit/mcp_agent_advanced.py`

### Launch
```bash
cd /home/linus/psirag/chainlit
./run_advanced.sh  # Advanced with self-reflection
# or
./run_mcp_agent.sh  # Simple version
```

### Example Output

**Question (English):**
> How does the mechanical hysteresis in the SwissFEL Aramis Undulator affect K-value reproducibility?

**Workflow Steps (visible in UI):**
1. 🔍 Parse Query: facility=swissfel, query="mechanical hysteresis Aramis Undulator K-value"
2. 📚 Search (Iteration 1): Found 5 results (avg score: 0.81)
3. 🤔 Evaluate: Quality=good, sufficient information
4. 🔗 Fetch Related: Retrieved 2 related articles
5. ✍️ Generate Answer (EN): Ollama generates in English

**Result:**
```markdown
The mechanical hysteresis in the SwissFEL Aramis undulator line creates
reproducibility challenges for K-values when gaps are reopened and reset...
[Natural language technical answer]

**Sources:**
1. [SwissFEL Einführung](https://acceleratorwiki.psi.ch/wiki/...)
2. [Undulator Technical Details](https://acceleratorwiki.psi.ch/wiki/...)

![Undulator gap hysteresis diagram](https://acceleratorwiki.psi.ch/...)
```

### Key Improvements Over Onyx

| Issue | Onyx Agent Mode | Chainlit Advanced Agent |
|-------|-----------------|-------------------------|
| Reasoning visible | ❌ Messy chain-of-thought | ✅ Clean collapsible steps |
| Duplicate citations | ❌ Same source cited multiple times | ✅ Deduplicated by URL |
| Language matching | ❌ Fixed language | ✅ Detects & matches user language |
| Quality control | ❌ No evaluation | ✅ Self-evaluates & retries |
| Related content | ❌ Not used | ✅ Automatic article_id follow-up |
| Answer quality | ❌ Raw context | ✅ Ollama-generated natural language |

### Configuration

Edit `mcp_agent_advanced.py`:
```python
OLLAMA_MODEL = "llama3.3:70b"  # Change model
MAX_ITERATIONS = 5              # Max retry attempts
```

### Query Refinement (Latest Update)

The advanced agent now implements **intelligent query refinement** on retries:

**How it works:**
1. Ollama evaluates search results quality based on scores and relevance
2. If quality is poor, it suggests a **refined query** (shorter, German technical terms)
3. Next iteration uses the refined query instead of repeating the same one

**Example refinement:**
```
Iteration 1: "storage electron buckets constant beam current storage ring"
Evaluation: Poor quality (avg score 0.52) → Refined query suggested
Iteration 2: "Speicherring Elektronenpakete Strahlstrom Topup" ✅ Better results
```

**Code location:**
- Lines 161-179: Evaluation prompt with refinement examples
- Lines 208-226: State update to use refined query
- UI displays: `**Refined Query:** `Speicherring Elektronenpakete Strahlstrom Topup``

### Limitations
- Language detection is simple (word-based heuristic)
- No conversation memory (stateless)
- No inline citations (only at end)
