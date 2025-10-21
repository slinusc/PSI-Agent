"""
Prompt Templates for LangGraph Agent Nodes

All prompts are centralized here to make it easy to iterate on prompt engineering
without touching business logic. Each prompt preserves the EXACT wording from the
original implementation to ensure behavior doesn't change.

All prompts accept:
- system_context: Complete system context string (identity, date/time, guidelines)
- **kwargs: node-specific context strings
"""


def prompt_decide_tools(
    system_context: str,
    query: str,
    tools_text: str,
    history_context: str = "",
    files_context: str = ""
) -> str:
    """
    Prompt for deciding if tools are needed.

    Args:
        system_context: Complete system context string
        query: User's question
        tools_text: Formatted tool descriptions
        history_context: Optional conversation history
        files_context: Optional uploaded files context

    Returns:
        Complete prompt string
    """
    return f"""{system_context}

**Task:** Decide if you should use tools to answer this question.

{history_context}{files_context}
**Current User Question:** {query}

**Available Tools:**
{tools_text}

**Decision Rules (IMPORTANT: Check conversation history first):**

**FIRST: Check if the answer is already in the conversation history:**
- If the user is asking a **follow-up question** about information that was ALREADY retrieved in previous messages, DO NOT use tools again
- Look for references to specific IDs mentioned in conversation history (e.g., "SARUN12", "ELOG #12345", article IDs)
- If the user asks "give me the complete entry for X" and X was already retrieved, use the history context
- If the user asks "tell me more about X" where X is in conversation history, use the existing context
- Examples of follow-up questions that should NOT use tools:
  - "Can you give me the complete ELOG entry for SARUN12?" (if SARUN12 was already mentioned in recent conversation)
  - "Tell me more details about that entry" (referring to previously discussed entry)
  - "What was the full text?" (referring to previous search results)

**SECOND: When to use tools (default for new queries):**
- **DEFAULT: Use tools** for NEW questions that require current, external, or additional information not in conversation history
- Use tools if the question asks about real-time data (weather, news, prices, events, etc.)
- Use tools for PSI-specific information (accelerators, operations, logs) that hasn't been retrieved yet
- Use tools if the conversation history doesn't contain sufficient detail to answer

**When NOT to use tools:**
- Pure greetings: "hello", "hi", "thanks"
- Follow-up questions about information already in conversation history
- **Questions about uploaded files or images** - answer directly using the file content provided above
- Conversation meta-questions: "what did I just ask?", "summarize our conversation"

Reply with JSON only:
{{
  "needs_tools": true/false,
  "reasoning": "brief explanation"
}}
"""


def prompt_select_tools(
    system_context: str,
    query: str,
    tools_text: str,
    history_context: str = "",
    refinement_context: str = ""
) -> str:
    """
    Prompt for selecting which tools to call.

    Structured in sections:
    1. General strategy (minimal arguments, refinement approach)
    2. Tool-specific guidelines (easy to add/remove tools)

    Args:
        system_context: Complete system context string
        query: User's question
        tools_text: Detailed tool descriptions with parameters
        history_context: Optional conversation history for extracting context (IDs, references)
        refinement_context: Optional refinement suggestion from previous attempt

    Returns:
        Complete prompt string
    """
    return f"""{system_context}

**Task:** Select which tools to call to answer the user's question.

{history_context}
**Current User Question:** {query}

**Available Tools:**
{tools_text}

{refinement_context}

**Context Extraction from Conversation History:**
- If the user asks about a specific entry, ID, or reference mentioned in the conversation history above, extract that information
- Look for ELOG IDs (e.g., "#39109", "SARUN12"), article IDs, or other identifiers
- Use the appropriate tool with the extracted ID to fetch complete information
- Example: "show me the full entry" → look in history for the entry ID, then use get_elog_thread or search_elog with that ID

**General Strategy:**
- Start with minimal arguments - only use REQUIRED parameters and those essential for the query
- Optional parameters should only be added if specifically mentioned in the user's question
- If initial results are too generic, refine with additional filters in a follow-up tool call
- Use the elog tool for any questions about incidents, events, or operational history.
- Use the accwiki tool for questions about accelerator facilities.
- Use web-search tools for current events, news, weather, or general external info
- Use multiple tools in sequence when it makes sense to narrow down or cross-reference results
- Be specific with parameter values (use exact enum options shown above)

**Date Handling:**
- Use the current date from the system context above to calculate relative dates
- "today" = current date
- "yesterday" = subtract 1 day from current date
- "last week" = subtract 7 days from current date for `since` parameter
- "last month" = subtract 30 days from current date
- "last weekend" or "this past weekend":
  * If today is Monday: Saturday and Sunday were 3 and 2 days ago
  * If today is Tuesday: Saturday and Sunday were 4 and 3 days ago
  * If today is Wednesday: Saturday and Sunday were 5 and 4 days ago
  * If today is Thursday-Sunday: most recent Saturday-Sunday
  * Example: Today is Monday 2025-10-21 → last weekend = 2025-10-18 (Sat) to 2025-10-19 (Sun)
  * Calculate by subtracting the correct number of days from current date
- Always use ISO format YYYY-MM-DD for date parameters

**Tool-Specific Guidelines:**

**search_accelerator_knowledge (AccWiki):**
- Extract facility from query: "hipa", "proscan", "sls", or "swissfel"
- Use "all" only if query explicitly asks about multiple facilities
- Retriever: Default to "dense" unless query needs exact term matching
- For SLS queries, use "sls" as the accelerator parameter
- Use tools for documentation, procedures, technical details about accelerators

**search_elog (ELOG):**
- Used for operational logs, incidents, and recent events
- Extract filters from query: category, system, domain, date range
- Date filters: Only use `since`/`until` if time range is mentioned
- Category examples: "Problem", "Shift", "Info", "Solution"
- **max_results parameter (CRITICAL for temporal queries):**
  * For summaries ("summarize last weekend", "what happened last week"): Use max_results=50-100 to ensure full coverage
  * For specific searches ("beam dump issues"): Use default (20) or lower
  * ELOG returns chronologically (newest first), so large max_results ensures you get entries from entire time period
  * Example: Weekend summary needs 50+ to cover both days, not just the most recent day
- Use tools for questions about specific events, incidents, or operational history

**get_elog_thread (ELOG):**
- Used to fetch a COMPLETE ELOG entry with all details and conversation thread
- REQUIRED parameter: entry_id (integer) - the ELOG entry number
- Use this when user asks for "full entry", "complete details", or references a specific ELOG ID
- Extract entry_id from conversation history or from the user's question
- Example: User mentions "ELOG #39109" or "SARUN12" → use get_elog_thread with entry_id: 39109

**Web Search Tools:**
- For current events, weather, news, or external information
- Keep queries concise and focused
- Avoid optional parameters unless critical

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
    summary_text: str,
    tool_calls_text: str = "",
    system_context: str = ""
) -> str:
    """
    Prompt for evaluating if tool results are adequate.

    Args:
        query: User's question
        summary_text: Summary of tool results
        tool_calls_text: Optional summary of what tools were called with what parameters
        system_context: System context including current date (needed for temporal validation)

    Returns:
        Complete prompt string
    """
    tool_calls_section = f"""
**Tools Called:**
{tool_calls_text}
""" if tool_calls_text else ""

    context_section = f"{system_context}\n\n" if system_context else ""

    return f"""{context_section}Evaluate if the tool results provide sufficient data to answer the user's question.

**User Question:** {query}
{tool_calls_section}
**Results from Tools:**
{summary_text}

**Evaluation Criteria:**

Tools return **structured JSON data** (entries, records, search results, etc.), NOT formatted answers.

Mark as **ADEQUATE** if:
- Tool returned relevant structured data (entries, hits, records) that contain information to answer the question
- The data is relevant to the question, even if it needs formatting/synthesis
- There are results, even if they need to be presented in a specific format

Mark as **INADEQUATE** only if:
- No results returned (empty dataset)
- Results are completely irrelevant to the question
- Tool error or missing critical data fields
- Wrong tool was called (e.g., used web search when ELOG was needed)
- **Wrong date range**: If user asked for "last weekend" or specific time period, check if result timestamps match that period

**Remember**: Your job is to check if DATA exists, not if it's formatted nicely. Formatting happens in the next step.

**Refinement Suggestions (only if inadequate):**
- Use different tool or parameters
- Add/modify filters or search terms
- Expand or narrow the search scope
- **Fix date parameters**: If dates are wrong, recalculate correct since/until values based on the current date and user's intent

Reply with JSON only:
{{
  "adequate": true/false,
  "reasoning": "brief explanation of data availability",
  "refinement": "specific parameter changes if inadequate"
}}
"""


def prompt_answer_with_tools(
    system_context: str,
    query: str,
    context_text: str,
    references_text: str,
    images_text: str
) -> str:
    """
    Prompt for generating final answer using tool results.

    Structured in sections:
    1. General instructions (apply to all tools)
    2. Tool-specific formatting (easy to add/remove tools)

    Args:
        system_context: Complete system context string
        query: User's question
        context_text: Formatted context from tools
        references_text: Source references
        images_text: Available images

    Returns:
        Complete prompt string
    """
    return f"""{system_context}

**Task:** Answer the user's question using the provided context.

**User Question:** {query}

**Context from Tools:**
{context_text}

**Available Source References:**
{references_text}
{images_text}

**General Instructions:**
- **CRITICAL: Match the language of the user's question EXACTLY:**
  * If the user question is in English → respond in English
  * If the user question is in German → respond in German
  * The language of source documents or ELOG entries does NOT matter - only the user's question language
  * Example: User asks "What happened?" (English) but ELOG has German text → still answer in English
- Be concise and technical (2-4 paragraphs)
- Ground your answer in the provided context
- Cite sources with clickable URLs
- If context is insufficient, acknowledge this clearly

**Formatting Guidelines:**

**Citations (General):**
- Use domain name as link text: [domain.com](URL)
- Example: "According to [bbc.com](https://www.bbc.com/weather/1668341)..."
- NOT: "According to [source description](URL)" or "[Web-1]"

**Images:**
- Include attached images in your answer when relevant
- Insert inline using: ![Image caption](image_url)
- Place in relevant paragraph, not at the end

**Math and Currency:**
- Currency: Write in plain text without $ symbols: "111,431 USD" or "71.4 billion USD"
- Math equations: Wrap with two dollar signs: $$formula$$

**Tool-Specific Formatting:**

**ELOG Entries (from search_elog, get_elog_thread):**

**Essential Fields to Always Include:**
- **Date/Time**: Use the "Date" field from the context (NOT times mentioned in content)
- **Author**: Entry creator
- **Category**: Entry type (Problem, Shift, Info, etc.)
- **System/Domain**: Technical classification
- **Effect**: Impact description
- **Content**: Full body_clean text (do NOT summarize unless user asks for summary)
- **Link**: Clickable URL using format `[elog-gfa.psi.ch/ID](URL)`

**Format Flexibility:**
- Use your judgment on how to present this information based on the user's question
- For "show me the entry" or "full details" → Use detailed structured format (tables work well)
- For "what happened" or summary questions → Present naturally in prose with key metadata
- Adapt formatting to make information clear and readable

**DISPLAYING ATTACHMENTS:**
Display images **INLINE** using `![](url)` only when:
1. The body_clean content **mentions** screenshots/images/plots (e.g., "see screenshot", "image shows")
2. The user **explicitly asks** for images (e.g., "show screenshots", "include images")

Otherwise, display as **clickable links**: `**Attachments:** [filename](url), [filename2](url2)`

**AccWiki/Knowledge Base (from search_accelerator_knowledge):**
- Cite with facility name if available: "According to SLS documentation..."
- Include article title if relevant
- Always provide clickable link

**Web Search Results (from web search tools):**
- **The "Content:" field contains the actual answer data** - read it carefully to extract specific information (prices, dates, facts, numbers)
- Answer the user's question directly using the data from the Content field
- Use domain name in citation: [domain.com](URL)
- Include publication date if available
- If multiple sources provide the same information, cite the most relevant one

**Answer:**
"""


def prompt_answer_no_tools(
    system_context: str,
    query: str,
    history_context: str = "",
    files_context: str = ""
) -> str:
    """
    Prompt for generating answer without using tools.

    Args:
        system_context: Complete system context string
        query: User's question
        history_context: Optional conversation history
        files_context: Optional full files context with content

    Returns:
        Complete prompt string
    """
    return f"""{system_context}

**Task:** Answer this question using your knowledge, the conversation history, and any uploaded files.

{history_context}{files_context}
**Current Question:** {query}

**Instructions:**

**For Follow-Up Questions:**
- **CAREFULLY examine the conversation history above** - it may contain the complete information needed to answer
- If the user is asking for "complete" or "full" details about something mentioned in the history, extract and present that information
- Look for specific IDs, entries, or references in the conversation history (e.g., ELOG IDs, article IDs, event names)
- If the user asks "tell me more about X" and X is in the conversation history, provide additional details from that context
- **Citations**: When using information from conversation history that originally came from tools (ELOG, AccWiki, web search), maintain the original source citations and URLs

**General Instructions:**
- **CRITICAL: Match the language of the user's question EXACTLY:**
  * If the user question is in English → respond in English
  * If the user question is in German → respond in German
  * The language of source documents or conversation history does NOT matter - only the user's current question language
  * Example: User asks "What happened?" (English) but history has German → still answer in English
- Be comprehensive when the user asks for "complete" or "full" information - don't summarize unnecessarily
- If the conversation history contains the answer, use it - don't say you need to search again
- If uploaded files are provided above, use that information to answer the question
- For documents, the full text is provided in the context
- For images, describe what you see if the question is about the image
- For math equations, wrap them with TWO dollar signs on each side: $$formula$$
- If information is truly missing and not in history, then acknowledge you would need to search

**Answer:**
"""


def prompt_answer_with_vision(
    system_context: str,
    query: str,
    image_count: int,
    history_context: str = ""
) -> str:
    """
    Prompt for generating answer using vision model with uploaded images.

    Args:
        system_context: Complete system context string
        query: User's question
        image_count: Number of images available
        history_context: Optional conversation history

    Returns:
        Complete prompt string
    """
    return f"""{system_context}

**Task:** Analyze the uploaded image(s) and answer the user's question.

{history_context}
**User Question:** {query}

**Images Available:** {image_count} image(s) provided below

**Instructions:**
- **CRITICAL: Match the language of the user's question EXACTLY:**
  * If the user question is in English → respond in English
  * If the user question is in German → respond in German
- Carefully examine all image(s) provided
- Answer the user's specific question about the image(s)
- Describe relevant visual details that help answer the question
- Be specific, detailed, and technical in your description
- If multiple images are provided, compare and contrast if relevant to the question
- For diagrams or technical images, explain the components, labels, and relationships
- For scientific images, identify key features and provide technical analysis
- For math equations in images, wrap LaTeX formulas with TWO dollar signs: $$formula$$

**Answer:**
"""
