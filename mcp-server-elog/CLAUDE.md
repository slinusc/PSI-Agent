# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MCP server providing intelligent search and analysis tools for SwissFEL ELOG entries. Uses direct ELOG API integration (no ElasticSearch) with smart semantic reranking via cross-encoder model.

**Key design decision:** Direct ELOG API instead of ElasticSearch because ELOG is updated daily - always fresh data, no sync lag, simpler infrastructure.

## Development Commands

### Setup
```bash
pip install -r requirements.txt
```

### Testing
```bash
# Run basic tool tests
python test_elog_tools.py

# Run advanced scenario tests
python test_advanced.py
```

### Running Tests
- Tests connect to live ELOG at `https://elog-gfa.psi.ch/SwissFEL+Commissioning`
- Test results are saved to `test_results/session_YYYYMMDD_HHMMSS/`
- No mocking - all tests use real ELOG API

## Architecture

### Core Components

**4 specialized search tools** ([elog_tools.py](elog_tools.py)):
1. `search_elog()` - Basic keyword/regex search with optional reranking
2. `search_elog_temporal()` - Time-range incident analysis with importance scoring
3. `search_elog_device()` - Device-specific queries (dual strategy: section + text)
4. `get_elog_thread()` - Thread navigation (parent/child message traversal)

**Supporting modules:**
- [logbook.py](logbook.py) - ELOG Python API client (878 lines, provided)
- [elog_reranker.py](elog_reranker.py) - Semantic reranker using `cross-encoder/ms-marco-MiniLM-L6-v2`
- [elog_constants.py](elog_constants.py) - Filter constants (15 categories, 18 systems, 9 domains)

### Data Flow
```
User Query
    ↓
ELOG API search (keyword/regex matching)
    ↓
Parallel bulk read (ThreadPoolExecutor, 10 workers)
    ↓
Smart reranking (cross-encoder + time decay)
    ↓
Top-K results
```

**Typical timings:** ~4-6s total (0.5s search + 2-3s parallel read + 1-2s reranking)

### Critical Performance Optimization

**Parallel bulk reading is essential** - Sequential reads would be 10x slower:
- Uses `ThreadPoolExecutor` with 10 workers
- 50 entries: ~2-3s parallel vs ~20-30s sequential
- See `_bulk_read_parallel()` in [elog_tools.py](elog_tools.py)

## Search Capabilities

### Regex Pattern Support
The ELOG API supports regex patterns for AND logic:
- `"beam.*energy"` finds entries with both "beam" AND "energy" (any order)
- `"laser.*power.*MW"` finds entries with all three terms
- Auto-detected when pattern contains `.*`

**Common patterns:**
```python
# Equipment searches
"undulator.*gap"              # Undulator gap settings
"BPM.*readback"               # Beam position monitor readbacks
"klystron.*power"             # Klystron power measurements

# Problem searches
"laser.*problem"              # Laser-related problems
"beam.*lost"                  # Beam loss events
"interlock.*trip"             # Interlock trips

# Measurement searches
"energy.*6.0"                 # Energy around 6.0 GeV
"current.*200"                # Current around 200 μA
```

### Attribute Filters
ELOG has structured metadata - use [elog_constants.py](elog_constants.py) for valid values.

**Categories (15 values):**
- Info, Problem, Pikett, Access
- Measurement summary, Shift summary, Schicht-Übergabe
- Tipps & Tricks, Überbrückung, Schicht-Auftrag
- RC exchange minutes, DCM minutes
- Laser- & Gun-Performance Routine, Weekly reference settings, Seed laser operation

**Systems (18 values):**
- RF, Controls, Diagnostics, Safety, Laser, Operation
- Feedbacks, Insertion-devices, Magnet Power Supplies, Photonics
- Vacuum, Timing & Sync, Beamdynamics, PLC
- Electric supply, Water cooling & Ventilation, Other, Unknown

**Domains (9 values):**
- Injector, Linac1, Linac2, Linac3
- Aramis, Aramis Beamlines
- Athos, Athos Beamlines
- Global

**Preset filters in [elog_constants.py](elog_constants.py):**
```python
from elog_constants import FILTER_PRESETS

FILTER_PRESETS["rf_problems"]        # {"Category": "Problem", "System": "RF"}
FILTER_PRESETS["safety_incidents"]   # {"Category": "Problem", "System": "Safety"}
FILTER_PRESETS["aramis_issues"]      # {"Category": "Problem", "Domain": "Aramis"}
FILTER_PRESETS["injector_problems"]  # {"Category": "Problem", "Domain": "Injector"}
FILTER_PRESETS["shift_summaries"]    # {"Category": "Shift summary"}
FILTER_PRESETS["performance_checks"] # {"Category": "Laser- & Gun-Performance Routine"}
```

**Filter usage:**
```python
# Single filter
result = search_elog(
    logbook=logbook,
    query="beam dump",
    filters={"Category": "Problem"}
)

# Multiple filters (AND logic)
result = search_elog(
    logbook=logbook,
    query="RF fault",
    filters={
        "Category": "Problem",
        "System": "RF",
        "Domain": "Aramis"
    }
)

# OR logic requires multiple queries
results_problem = search_elog(logbook, query="RF", filters={"Category": "Problem"})
results_pikett = search_elog(logbook, query="RF", filters={"Category": "Pikett"})
# Then merge and deduplicate results
```

### Scope Control
When searching, you can control where to look:
- `scope="subtext"` - Search only in message body (default)
- `scope="attribname"` - Search only in attributes (title, category, system, etc.)
- `scope="all"` - Search everywhere

## Reranker Details

**Model:** `cross-encoder/ms-marco-MiniLM-L6-v2`
- Fast inference (~50ms per query-doc pair)
- Good multilingual support (English/German)
- Lazy loading - model only loaded when `rerank=True`

**Scoring features:**
1. **Semantic similarity** - Cross-encoder scores query-document relevance
2. **Time decay** - Recent entries (<48h) get 2x boost: `score * (1.0 + exp(-hours/48))`
3. **Diversity constraints** - Max N per category to avoid category clustering

**Configuration in [elog_reranker.py](elog_reranker.py):**
```python
RerankConfig(
    model_name="cross-encoder/ms-marco-MiniLM-L6-v2",
    target_k=10,              # Return top-K
    time_decay_hours=48.0,    # Decay half-life
    max_per_category=5        # Diversity constraint
)
```

## Device Search Strategy

`search_elog_device()` uses dual strategy to find device mentions:

1. **Section field exact match** - Device name in "Section" attribute
2. **Body text mention** - Device name anywhere in message text
3. **Combine and deduplicate** - Merge results, remove duplicates

Example:
```python
# Device "SATUN18" will find:
# - Entries with Section="SATUN18" (official device field)
# - Entries mentioning "SATUN18" in text (related discussions)
```

With `include_related=True`, also searches for related devices (undulators, BPMs near the device).

## Temporal Analysis

`search_elog_temporal()` searches entries within a time range:

**Key features:**
- Always sorted chronologically (newest first)
- Date filtering done post-fetch (ELOG API date filter is unreliable)
- Optional attribute filters (e.g., `{"Category": "Problem", "System": "RF"}`)
- Returns aggregations by category, system, and domain

**Usage:**
```python
# Problems only
result = search_elog_temporal(
    logbook=logbook,
    since="2025-10-01",
    until="2025-10-07",
    filters={"Category": "Problem"},
    top_k=20
)

# All entries (no filter)
result = search_elog_temporal(
    logbook=logbook,
    since="2025-10-01",
    until="2025-10-07",
    filters=None,
    top_k=20
)
```

## Thread Navigation

ELOG entries can have parent/child relationships (replies):

```python
get_elog_thread(
    logbook=logbook,
    msg_id=12345,
    direction="both"  # "descendants", "ancestors", or "both"
)
```

Returns full conversation thread with proper ordering.

## Important Notes

### ELOG API Limitations
- **No OR logic in filters** - Must run multiple queries and merge results
- **Date format varies** - Accepts both `DD/MM/YYYY` and ISO8601
- **HTML parsing dependency** - Results parsed from HTML (fragile to UI changes)
- **Rate limiting** - Be respectful with parallel requests (max 10 workers)

### HTML Content Handling
All entries include both:
- `body` - Original HTML content
- `body_clean` - Cleaned text (HTML tags removed, whitespace normalized)

Use `body_clean` for LLM processing, `body` for rendering with attachments.

### Entry URLs
Each result includes `url` field pointing to direct ELOG entry:
```
https://elog-gfa.psi.ch/SwissFEL+Commissioning/12345
```

## Testing Strategy

**No mocking** - All tests use live ELOG API:
- Tests realistic query patterns
- Validates against actual data
- Results saved to `test_results/` for analysis

**Test categories:**
1. Basic search (with/without reranking, with filters)
2. Temporal analysis (incidents vs all entries)
3. Device search (section-only vs text-inclusive)
4. Thread navigation (descendants/ancestors/both)
5. Edge cases (empty query, no results, invalid IDs)

## ELOG API Quick Reference

### Basic Operations
```python
from logbook import Logbook

# Initialize
logbook = Logbook(
    hostname="https://elog-gfa.psi.ch",
    logbook="SwissFEL+Commissioning"
)

# Get message IDs
msg_ids = logbook.search("beam energy", n_results=50)
msg_ids = logbook.search({"Category": "Problem"}, n_results=100)

# Read single entry
message, attributes, attachments = logbook.read(msg_id)

# Attributes available:
# - $@MID@$: Message ID
# - Date: Entry date
# - Author: Entry author
# - Category, System, Domain: Structured metadata
# - Title/Subject: Entry title
# - Section, Beamline, Effect: Additional fields
```

### Search Methods
```python
# Text search with scope
msg_ids = logbook.search("beam energy", scope="subtext")    # Body text only (default)
msg_ids = logbook.search("Problem", scope="attribname")     # Attributes only
msg_ids = logbook.search("SATUN18", scope="all")            # Everywhere

# Regex patterns
msg_ids = logbook.search("beam.*energy")                    # AND logic
msg_ids = logbook.search("laser.*power.*MW")                # Multiple terms

# Attribute filters
msg_ids = logbook.search({"Category": "Problem"})
msg_ids = logbook.search({"System": "RF", "Domain": "Aramis"})
```

## Common Development Patterns

### Multi-Pattern Search with Deduplication
```python
# Search multiple patterns and merge
patterns = ["RF.*fault", "RF.*trip", "klystron.*problem"]
all_results = []
for pattern in patterns:
    result = search_elog(logbook, query=pattern, filters={"Category": "Problem"})
    all_results.extend(result['hits'])

# Deduplicate by elog_id
seen_ids = set()
unique_results = [hit for hit in all_results
                  if hit['elog_id'] not in seen_ids and not seen_ids.add(hit['elog_id'])]
```

### Time-Range Analysis
```python
from datetime import datetime, timedelta

# Last week's incidents
since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
result = search_elog_temporal(
    logbook=logbook,
    since=since,
    until=datetime.now().strftime("%Y-%m-%d"),
    focus="incidents"
)

print(f"Found {result['total_unique']} incidents")
print(f"By system: {result['aggregations']['system']}")
```

### Device Correlation
```python
# Find related device mentions
result = search_elog_device(
    logbook=logbook,
    device="SATUN18",
    include_related=True,  # Also search for nearby BPMs, undulators
    top_k=10
)

# Check related devices found
for device in result['related_devices']:
    print(f"Also mentioned: {device}")
```

## Performance Considerations

**Always use parallel reading:**
- The `_bulk_read_parallel()` function is critical for performance
- 10 workers is optimal (tested empirically)
- Don't increase beyond 10 to avoid overwhelming ELOG server

**Reranking trade-offs:**
- With reranking: ~4-6s total, best relevance
- Without reranking: ~3-4s total, chronological order
- Use `rerank=True` for semantic queries, `rerank=False` for temporal queries

**Result limits:**
- Fetch 2-3x more than needed: `n_results=30` → `top_k=10`
- Diminishing returns beyond n_results=100
- Large result sets (>100) increase latency significantly

## Next Steps

**MCP HTTP Server Integration:**
Create `server_http.py` that wraps the 4 tool functions as MCP tools.
Reference: `/home/linus/psirag/AccWikiGraphRAG/mcp-server/server_http.py`

The tools are designed with MCP in mind - simple function signatures, clear return types, comprehensive error handling.
