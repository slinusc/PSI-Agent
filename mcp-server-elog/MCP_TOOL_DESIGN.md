# MCP Tool Design for ELOG Server

## Current Tool Analysis

### Tool 1: `search_elog()` - General Search
**Purpose:** Keyword/regex search with semantic reranking

**Arguments:**
- `query` (required): Search string, supports regex patterns like "beam.*energy"
- `n_results` (default: 20): Fetch this many before reranking
- `rerank` (default: True): Apply semantic reranking
- `top_k` (default: 10): Return this many results
- `scope` (default: "subtext"): Where to search ("subtext", "attribname", "all")
- `filters` (optional): Attribute filters like `{"Category": "Problem", "System": "RF"}`
- `use_regex` (default: False): Explicitly enable regex (auto-detected if query contains `.*`)

**Issues for LLM:**
- Too many parameters (7 total)
- Confusion between `n_results` and `top_k`
- `use_regex` is redundant (auto-detected)
- `scope` requires understanding ELOG internals

---

### Tool 2: `search_elog_temporal()` - Time Range Search
**Purpose:** Find entries within a date range, chronologically sorted

**Arguments:**
- `since` (required): Start date (YYYY-MM-DD or ISO8601)
- `until` (required): End date (YYYY-MM-DD or ISO8601)
- `filters` (optional): Attribute filters
- `n_fetch` (default: 200): How many to fetch before date filtering
- `top_k` (default: 25): Return this many results

**Issues for LLM:**
- `n_fetch` is an implementation detail (shouldn't be exposed)
- Confusion between `n_fetch` and `top_k`

---

### Tool 3: `search_elog_device()` - Device-Specific Search
**Purpose:** Find entries about a specific device/component

**Arguments:**
- `device` (required): Device name (e.g., "SATUN18")
- `include_related` (default: True): Search both Section field and body text
- `n_results` (default: 30): Fetch this many
- `top_k` (default: 15): Return this many

**Issues for LLM:**
- Overlaps with `search_elog(query="SATUN18")`
- `include_related` is confusing (dual search strategy)
- Confusion between `n_results` and `top_k`

---

### Tool 4: `get_elog_thread()` - Thread Navigation
**Purpose:** Get conversation thread (replies/parents)

**Arguments:**
- `msg_id` (required): ELOG entry ID
- `direction` (default: "descendants"): "descendants", "ancestors", or "both"

**Issues for LLM:**
- `direction` parameter requires understanding thread structure
- Not commonly used in workflows

---

## Common Issues Across All Tools

1. **Internal parameters exposed**: `n_results`, `n_fetch`, `save_dir`, `save_attachments`, `save_session`
2. **Confusing naming**: `n_results` vs `top_k`, `n_fetch` vs `top_k`
3. **Redundant parameters**: `use_regex` (auto-detected), `scope` (rarely changed)
4. **Tool overlap**: Device search can be done with general search

---

## Proposed Simplified MCP Tools

### Option A: Minimal (2 Tools)

#### 1. `search_elog`
```python
{
  "query": str,                    # Required: Search text or regex pattern
  "since": str | null,             # Optional: Start date (YYYY-MM-DD)
  "until": str | null,             # Optional: End date (YYYY-MM-DD)
  "category": str | null,          # Optional: e.g., "Problem", "Info"
  "system": str | null,            # Optional: e.g., "RF", "Controls"
  "domain": str | null,            # Optional: e.g., "Aramis", "Athos"
  "max_results": int = 10          # How many results to return
}
```

**Rationale:**
- Single unified search tool
- Time range is optional (if omitted, searches all time)
- Flat structure for category/system/domain (no nested `filters` dict)
- Single `max_results` parameter (no confusion)
- Semantic reranking always on (it's smart)
- Auto-detects regex patterns

**Example Queries:**
```json
// General search
{"query": "RF problems", "max_results": 10}

// Time-range search
{"query": "beam dump", "since": "2025-10-01", "until": "2025-10-07"}

// Filtered search
{"query": "laser", "category": "Problem", "system": "Laser"}

// Device search
{"query": "SATUN18", "since": "2025-10-01", "max_results": 5}

// Recent incidents
{"since": "2025-10-06", "category": "Problem"}
```

#### 2. `get_elog_thread`
```python
{
  "message_id": int,               # Required: ELOG entry ID
  "include_replies": bool = True,  # Include reply chain
  "include_parents": bool = True   # Include parent chain
}
```

**Rationale:**
- Simpler boolean flags instead of "direction" enum
- Both default to True (get full thread)

---

### Option B: Moderate (3 Tools)

#### 1. `search_elog` - General/semantic search
```python
{
  "query": str,                    # Required: Search text or regex
  "category": str | null,
  "system": str | null,
  "domain": str | null,
  "max_results": int = 10
}
```

#### 2. `search_elog_by_date` - Temporal search
```python
{
  "since": str,                    # Required: YYYY-MM-DD
  "until": str,                    # Required: YYYY-MM-DD
  "category": str | null,
  "system": str | null,
  "domain": str | null,
  "max_results": int = 20
}
```

**Rationale:** Separate temporal search as distinct use case

#### 3. `get_elog_thread` - Same as Option A

---

### Option C: Maximum Simplicity (1 Tool)

#### `search_elog` - Universal search
```python
{
  "query": str | null,             # Optional: Search text (if omitted, returns recent)
  "message_id": int | null,        # Optional: Get specific entry + thread
  "since": str | null,
  "until": str | null,
  "category": str | null,
  "system": str | null,
  "domain": str | null,
  "max_results": int = 10
}
```

**Behavior:**
- If `message_id` provided → Get entry + thread
- If `query` provided → Semantic search
- If `since`/`until` provided → Time-range search
- Can combine: `query + since/until` → Recent entries matching query

**Rationale:** One tool to rule them all, LLM decides parameters

---

## Recommended Approach: **Option A (2 Tools)**

### Why Option A?

✅ **Pros:**
- Minimal cognitive load (just 2 tools)
- Unified search covers 80% of use cases
- Clear separation: search vs thread navigation
- Flat parameter structure (no nested dicts)
- Single `max_results` parameter (no confusion)
- Flexible enough for complex queries

❌ **Cons of other options:**
- Option B: More tools = more for LLM to choose from
- Option C: Too magical (behavior changes based on params)

---

## Implementation Changes Needed

### 1. Simplify `search_elog()` signature:
```python
def search_elog(
    logbook: Logbook,
    query: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
    system: Optional[str] = None,
    domain: Optional[str] = None,
    max_results: int = 10
) -> Dict[str, Any]:
```

**Changes:**
- Remove: `n_results`, `rerank`, `top_k`, `scope`, `filters`, `use_regex`
- Add: `since`, `until` (time range filtering)
- Replace `filters` dict with flat `category`, `system`, `domain` params
- Rename `top_k` → `max_results`
- Always: `rerank=True`, `scope="subtext"`, auto-detect regex

### 2. Remove `search_elog_temporal()`:
- Functionality absorbed into unified `search_elog()`
- When `since`/`until` provided → temporal search

### 3. Remove `search_elog_device()`:
- Just use `search_elog(query="SATUN18")`
- No special device logic needed

### 4. Simplify `get_elog_thread()`:
```python
def get_elog_thread(
    logbook: Logbook,
    message_id: int,
    include_replies: bool = True,
    include_parents: bool = True
) -> Dict[str, Any]:
```

**Changes:**
- Rename `msg_id` → `message_id` (clearer)
- Replace `direction` enum with boolean flags

---

## MCP Tool Definitions

### Tool 1: `search_elog`
```json
{
  "name": "search_elog",
  "description": "Search SwissFEL ELOG entries with semantic ranking. Supports text search, regex patterns, time ranges, and attribute filters.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search text or regex pattern (e.g., 'beam dump', 'RF.*fault'). Omit to search by filters/dates only."
      },
      "since": {
        "type": "string",
        "description": "Start date for time range (YYYY-MM-DD format). Optional."
      },
      "until": {
        "type": "string",
        "description": "End date for time range (YYYY-MM-DD format). Optional."
      },
      "category": {
        "type": "string",
        "description": "Filter by category (e.g., 'Problem', 'Info', 'Pikett'). Optional.",
        "enum": ["Info", "Problem", "Pikett", "Access", "Measurement summary",
                 "Shift summary", "Tipps & Tricks", "Überbrückung", "Schicht-Auftrag"]
      },
      "system": {
        "type": "string",
        "description": "Filter by system (e.g., 'RF', 'Controls', 'Safety'). Optional.",
        "enum": ["RF", "Controls", "Diagnostics", "Safety", "Laser", "Operation",
                 "Feedbacks", "Insertion-devices", "Vacuum", "Timing & Sync"]
      },
      "domain": {
        "type": "string",
        "description": "Filter by domain (e.g., 'Aramis', 'Athos', 'Injector'). Optional.",
        "enum": ["Injector", "Linac1", "Linac2", "Linac3", "Aramis",
                 "Aramis Beamlines", "Athos", "Athos Beamlines", "Global"]
      },
      "max_results": {
        "type": "integer",
        "description": "Maximum number of results to return. Default: 10.",
        "default": 10,
        "minimum": 1,
        "maximum": 50
      }
    }
  }
}
```

### Tool 2: `get_elog_thread`
```json
{
  "name": "get_elog_thread",
  "description": "Get full conversation thread for an ELOG entry, including replies and parent messages.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "message_id": {
        "type": "integer",
        "description": "ELOG message ID to get thread for"
      },
      "include_replies": {
        "type": "boolean",
        "description": "Include reply chain (descendants). Default: true.",
        "default": true
      },
      "include_parents": {
        "type": "boolean",
        "description": "Include parent chain (ancestors). Default: true.",
        "default": true
      }
    },
    "required": ["message_id"]
  }
}
```

---

## Workflow Examples

### Use Case 1: Find recent RF problems
```python
search_elog(
    query="RF fault",
    since="2025-10-01",
    category="Problem",
    system="RF",
    max_results=10
)
```

### Use Case 2: What happened last night?
```python
search_elog(
    since="2025-10-06",
    until="2025-10-07",
    category="Problem",
    max_results=20
)
```

### Use Case 3: Device status inquiry
```python
search_elog(
    query="SATUN18",
    since="2025-09-01",
    max_results=5
)
```

### Use Case 4: Explore thread
```python
# First, search returns message_id in results
result = search_elog(query="magnet failure")
msg_id = result['hits'][0]['elog_id']

# Then, get full thread
thread = get_elog_thread(message_id=msg_id)
```

---

## Migration Summary

**Before: 4 tools, 20+ parameters**
- `search_elog()` - 11 params
- `search_elog_temporal()` - 9 params
- `search_elog_device()` - 8 params
- `get_elog_thread()` - 6 params

**After: 2 tools, 9 parameters**
- `search_elog()` - 7 params (all simple)
- `get_elog_thread()` - 3 params (1 required)

**Reduction:** 55% fewer parameters, 50% fewer tools

---

## Next Steps

1. Refactor `search_elog()` to accept flat parameters + time range
2. Remove `search_elog_temporal()` and `search_elog_device()`
3. Simplify `get_elog_thread()` signature
4. Create MCP server wrapper (`server_http.py`) with 2 tools
5. Update tests and documentation


## Implementation Complete ✅

**File:** `elog_tools_simplified.py`

### Changes Made

1. ✅ **Unified `search_elog()`** with flat parameters
2. ✅ **Removed redundant tools**
3. ✅ **Simplified `get_elog_thread()`**

### Test Results
All 4 test scenarios passed successfully.

## Next Steps
1. Create MCP server wrapper (`server_http.py`)
2. Update documentation
