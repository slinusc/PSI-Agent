# LangGraph Agent Information Flow Design

## Overview

This document defines the information architecture for the LangGraph autonomous agent, separating **global context** (flows through all nodes) from **node-specific context** (computed per node).

## Design Principles

1. **Global context is computed once** and stored in state
2. **Node-specific context is computed only where needed**
3. **Prompts are managed separately** from business logic
4. **Context builders are reusable functions**

---

## Information Categories

### 1. Global State (Always Available)

These fields are set once at initialization and flow through all nodes:

```python
class AgentState(TypedDict):
    # Input
    query: str                              # User's question
    messages: List[Dict[str, Any]]          # Conversation history
    context_files: List[Dict[str, Any]]     # Uploaded files (PDFs, images)
    available_tools: Dict[str, Dict]        # Tool metadata
    mcp_sessions: Dict[str, Any]            # MCP connections

    # Configuration
    max_iterations: int                     # Max retry attempts
    system_context: str                     # GLOBAL: Date/time, assistant info

    # Workflow state (changes during execution)
    needs_tools: bool
    selected_tools: List[Dict]
    tool_results: List[Dict]
    iteration: int
    results_adequate: bool
    refinement_suggestion: Optional[str]
    final_answer: Optional[str]
```

**NEW: `system_context`** - Computed ONCE at initialization, contains:
- Current date and time
- Assistant role/identity
- General instructions that apply to all nodes

### 2. Node-Specific Context

Context that is **only relevant for specific nodes** should be computed locally:

| Context | Used By | Purpose |
|---------|---------|---------|
| Tool descriptions (summary) | `decide_tools_needed` | Quick tool list for decision |
| Tool descriptions (detailed) | `select_tools` | Full parameter schemas |
| Conversation history (truncated) | `decide_tools_needed`, `generate_answer_no_tools` | Recent context |
| File context (summary) | `decide_tools_needed` | File names only |
| File context (full) | `generate_answer_no_tools`, `generate_answer_with_tools` | Complete file content |
| Date calculation examples | `select_tools` | Help with date math |

---

## Proposed Architecture

### Phase 1: Extract Context Builders

Create `context_builders.py`:

```python
from datetime import datetime
from typing import List, Dict, Any

def build_system_context() -> str:
    """Build global system context (date/time, assistant identity)"""
    now = datetime.now()
    current_datetime = now.strftime("%A, %B %d, %Y at %H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    return f"""You are the PSI assistant at Paul Scherrer Institute.
Current Date and Time: {current_datetime} (Use {current_date} for date calculations)
"""

def build_conversation_context(messages: List[Dict], max_messages: int = 6) -> str:
    """Build conversation history context"""
    if not messages:
        return ""

    recent = messages[-max_messages:]
    lines = [f"{m['role'].capitalize()}: {m['content'][:200]}" for m in recent]
    return f"**Recent Conversation:**\n" + "\n".join(lines)

def build_files_context_summary(context_files: List[Dict]) -> str:
    """Build file context summary (names only)"""
    if not context_files:
        return ""

    lines = []
    for f in context_files:
        file_type = f.get('type', 'unknown')
        file_name = f.get('name', 'unknown')
        if file_type == 'image':
            lines.append(f"- Image: {file_name}")
        else:
            preview = f.get('preview', '')[:100]
            lines.append(f"- Document: {file_name} - {preview}")

    return f"**Uploaded Files:**\n" + "\n".join(lines)

def build_files_context_full(context_files: List[Dict]) -> str:
    """Build full file context with content"""
    if not context_files:
        return ""

    parts = []
    for f in context_files:
        file_type = f.get('type', 'unknown')
        file_name = f.get('name', 'unknown')

        if file_type == 'image':
            base64_data = f.get('base64', '')
            if base64_data:
                parts.append(f"**Image: {file_name}**\n[Image data available]")
            else:
                parts.append(f"**Image: {file_name}**\n[Image uploaded]")
        else:
            preview = f.get('preview', '')
            if preview:
                parts.append(f"**Document: {file_name}**\n{preview}")
            else:
                parts.append(f"**Document: {file_name}**\n[No preview]")

    return f"**Uploaded Files:**\n" + "\n".join(parts)

def build_tools_context_summary(available_tools: Dict[str, Dict]) -> str:
    """Build tool list summary for decision-making"""
    if not available_tools:
        return "No tools available"

    lines = [f"- {name}: {info.get('description', '')[:100]}"
             for name, info in available_tools.items()]
    return "\n".join(lines)

def build_tools_context_detailed(available_tools: Dict[str, Dict]) -> str:
    """Build detailed tool descriptions with parameters"""
    parts = []
    for tool_name, tool_info in available_tools.items():
        desc = f"**{tool_name}**\n"
        desc += f"  Description: {tool_info.get('description', '')}\n"

        schema = tool_info.get("input_schema", {})
        if "properties" in schema:
            desc += "  Parameters:\n"
            for param_name, param_info in schema["properties"].items():
                param_type = param_info.get("type", "any")
                desc += f"    - {param_name} ({param_type})"

                if "enum" in param_info:
                    desc += f" [options: {', '.join(param_info['enum'][:5])}]"

                if param_name in schema.get("required", []):
                    desc += " [REQUIRED]"

                desc += "\n"

        parts.append(desc)

    return "\n".join(parts)
```

### Phase 2: Extract Prompts

Create `prompts.py`:

```python
"""
Prompt templates for LangGraph agent nodes.

Each prompt function takes:
- system_context: str (global context with date/time)
- **kwargs: node-specific context

This separates prompt engineering from business logic.
"""

def prompt_decide_tools(
    system_context: str,
    query: str,
    tools_summary: str,
    conversation_context: str = "",
    files_context: str = ""
) -> str:
    return f"""{system_context}

{conversation_context}{files_context}
**Current User Question:** {query}

**Available Tools:**
{tools_summary}

**Decision Rules (IMPORTANT: Default to using tools):**
- **DEFAULT: Use tools** unless you are 100% certain you can answer completely from training data
- Use tools for ANY question that could benefit from current, external, or additional information
- Use tools if the question asks about real-time data (weather, news, prices, events, etc.)
- Use tools for PSI-specific information (accelerators, operations, logs)
- **ONLY skip tools if:** the question is purely conversational ("hello", "thank you") or asks about previous conversation history or uploaded files

**When NOT to use tools (very rare):**
- Pure greetings: "hello", "hi", "thanks"
- Conversation references: "what did I just ask?"
- **Questions about uploaded files or images** - answer directly using the file content provided above
- Simple definitions you're 100% sure about AND don't need verification

Reply with JSON only:
{{
  "needs_tools": true/false,
  "reasoning": "brief explanation"
}}
"""

def prompt_select_tools(
    system_context: str,
    query: str,
    tools_detailed: str,
    refinement_context: str = ""
) -> str:
    # Extract current date from system_context for inline reference
    import re
    date_match = re.search(r'\(Use (\d{4}-\d{2}-\d{2})', system_context)
    current_date = date_match.group(1) if date_match else "YYYY-MM-DD"

    return f"""{system_context}

**User Question:** {query}

**Available Tools:**
{tools_detailed}

{refinement_context}

**Guidelines:**
- For questions about SLS, extract "sls" as the accelerator parameter
- Use search_accelerator_knowledge for technical documentation
- Use search_elog for operational logs or recent events
- **For date-based queries:** Calculate dates relative to current date ({current_date})
  - "today" = {current_date}
  - "yesterday" = subtract 1 day
  - "last week" = subtract 7 days from today for `since` parameter
  - "last month" = subtract 30 days
- Only use optional arguments only when specifically needed
- If it makes sense, use multiple tools in sequence to refine results
- Be specific with parameters (use enum values shown above)

Reply with JSON only:
{{
  "tools": [
    {{
      "tool_name": "exact_tool_name",
      "arguments": {{"param": "value"}},
      "reasoning": "why this tool"
    }}
  ]
}}
"""

def prompt_evaluate_results(
    query: str,
    results_summary: str
) -> str:
    """Evaluation doesn't need system context (internal decision)"""
    return f"""Evaluate if the tool results can answer the user's question.

**User Question:** {query}

**Results from Tools:**
{results_summary}

**Evaluation:**
- Are the results relevant to the question?
- Is there enough context information to provide a good answer?
- If not, what's missing or how should we refine the search?

Reply with JSON only:
{{
  "adequate": true/false,
  "reasoning": "brief explanation",
  "refinement": "if inadequate, suggest how to improve"
}}
"""

def prompt_answer_with_tools(
    system_context: str,
    query: str,
    context_text: str,
    references_text: str,
    images_text: str,
    language: str
) -> str:
    return f"""{system_context}

**User Question:** {query}

**Context from Tools:**
{context_text}

**Available Source References:**
{references_text}
{images_text}

**Instructions:**
- Answer in {language}
- Be concise and technical (2-4 paragraphs)
- **IMPORTANT**: When citing sources, use the domain name as the link text in markdown format
- **ELOG ENTRIES**: Always include ELOG ID, date/time, author, category, system
- Place images inline using ![caption](url)
- For currency: use "111,431 USD" (no dollar signs)
- For math equations: wrap with two dollar signs on each side
- If context is insufficient, acknowledge this
- Make sure every cited source includes the clickable URL

**Answer:**
"""

def prompt_answer_no_tools(
    system_context: str,
    query: str,
    conversation_context: str = "",
    files_context: str = ""
) -> str:
    return f"""{system_context}

{conversation_context}{files_context}
**Current Question:** {query}

**Instructions:**
- Be concise and accurate
- If this requires PSI-specific data, say you need to search the knowledge base
- If the user is referring to previous messages, use the conversation history above
- **If uploaded files are provided above, use that information to answer the question**
- For documents, the full text is provided in the context
- For math equations: wrap with two dollar signs on each side

**Answer:**
"""
```

### Phase 3: Refactor Nodes

Update node functions to use context builders and prompts:

```python
from context_builders import (
    build_system_context,
    build_conversation_context,
    build_files_context_summary,
    build_tools_context_summary
)
from prompts import prompt_decide_tools

async def decide_tools_needed(state: AgentState) -> AgentState:
    """Decide if tools are needed to answer the question"""

    # Extract state
    query = state["query"]
    system_context = state["system_context"]  # Already built!
    available_tools = state["available_tools"]
    messages = state.get("messages", [])
    context_files = state.get("context_files", [])

    # Build node-specific context
    tools_summary = build_tools_context_summary(available_tools)
    conversation_context = build_conversation_context(messages)
    files_context = build_files_context_summary(context_files)

    # Build prompt
    prompt = prompt_decide_tools(
        system_context=system_context,
        query=query,
        tools_summary=tools_summary,
        conversation_context=conversation_context,
        files_context=files_context
    )

    # Call LLM
    llm = ChatOllama(model="gpt-oss:20b-65k", base_url="http://localhost:11434", temperature=0.1)
    response = await llm.ainvoke([HumanMessage(content=prompt)])

    # Parse and update state
    # ... (existing parsing logic)

    return state
```

---

## Migration Plan

### Step 1: Create New Files
- [ ] Create `context_builders.py` with all context building functions
- [ ] Create `prompts.py` with all prompt templates
- [ ] Add unit tests for context builders

### Step 2: Update AgentState
- [ ] Add `system_context: str` field to AgentState
- [ ] Update `process_query()` to build system_context once
- [ ] Pass system_context to initial state

### Step 3: Refactor Nodes (one at a time)
- [ ] Refactor `decide_tools_needed`
- [ ] Refactor `select_tools`
- [ ] Refactor `evaluate_results`
- [ ] Refactor `generate_answer_with_tools`
- [ ] Refactor `generate_answer_no_tools`

### Step 4: Remove Old Code
- [ ] Remove inline context building from nodes
- [ ] Remove datetime imports from nodes
- [ ] Clean up redundant functions

### Step 5: Testing
- [ ] Test each node individually
- [ ] Test full graph execution
- [ ] Verify prompts haven't changed behavior

---

## Benefits

1. **Maintainability**: Prompts in one file, easy to iterate
2. **Performance**: System context computed once, not 4 times
3. **Testability**: Context builders can be unit tested
4. **Clarity**: Clear separation of global vs node-specific context
5. **Reusability**: Context builders can be reused across nodes
6. **DRY**: No repeated date/time computation

---

## Current Issues to Fix

1. **Date/time computed 4 times** (decide_tools, select_tools, generate_answer_with_tools, generate_answer_no_tools)
2. **Tool descriptions built 2 times** (decide_tools, select_tools)
3. **File context built 3 times** (decide_tools, generate_answer_no_tools, generate_answer_with_tools)
4. **History context built 2 times** (decide_tools, generate_answer_no_tools)
5. **Prompts embedded in business logic** - hard to iterate on prompt engineering
6. **No clear separation** of global vs node-specific context

All of these are solved by the proposed architecture.
