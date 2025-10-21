"""
Simple Autonomous Agent using LangGraph

Flow:
1. User asks question
2. Decide if tools are needed
3. If yes: select tools → call tools → evaluate results
4. If results inadequate: refine and retry (max 3 attempts)
5. Generate final answer with sources
"""

import json
import logging
from typing import Dict, Any, List, Optional, Annotated, Literal
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Import context builders and prompts at module level
import context_builders
import prompts

logger = logging.getLogger("psi.chainlit.langgraph_agent")


# ============================================================================
# Model Configuration
# ============================================================================

# Centralized model configuration for each node
# Change these to experiment with different models for different tasks
NODE_MODELS = {
    "decide_tools": {
        "model": "gpt-oss:20b-65k",
        "temperature": 0.1,
        "base_url": "http://localhost:11434"
    },
    "select_tools": {
        "model": "gpt-oss:20b-65k",
        "temperature": 0.2,
        "base_url": "http://localhost:11434"
    },
    "evaluate_results": {
        "model": "gpt-oss:20b-65k",
        "temperature": 0.1,
        "base_url": "http://localhost:11434"
    },
    "generate_answer_with_tools": {
        "model": "gpt-oss:20b-65k",
        "temperature": 0.3,
        "base_url": "http://localhost:11434"
    },
    "generate_answer_no_tools": {
        "model": "gpt-oss:20b-65k",
        "temperature": 0.3,
        "base_url": "http://localhost:11434"
    },
    "vision_answer": {
        "model": "gemma3:12b",
        "temperature": 0.3,
        "base_url": "http://localhost:11434"
    }
}


# ============================================================================
# Utility Functions
# ============================================================================

def convert_latex_delimiters(text: str) -> str:
    """Convert LaTeX delimiters to Chainlit/KaTeX compatible format and escape currency."""
    import re

    original_text = text

    # FIRST: Escape dollar signs that are part of currency (before any LaTeX processing)
    # Match patterns like: $123, $123,456, $123.45, $123,456.78
    # Handle bold/italic markdown: **$123**, *$456*
    # Don't match already escaped: \$123
    text = re.sub(r'(?<!\\)(\**)(\$)(\d[\d,]*\.?\d*)(\s*)(USD|EUR|CHF|GBP|BTC|ETH)?(\**)',
                  r'\1\\\2\3\4\5\6', text)

    # First, fix escaped dollar signs: \$$ -> $$ and \$ -> $
    # The LLM outputs literal backslash-dollar, so we need to match that
    text = text.replace('\\$$', '$$')  # Match actual backslash-dollar-dollar
    # Note: We DON'T unconditionally replace \$ anymore since we just added them for currency

    if text != original_text:
        logger.debug(f"LaTeX conversion: processed currency and delimiters")

    # Convert display math: \[ ... \] or standalone [ ... ] to $$ ... $$
    # Match brackets on their own lines (display math)
    text = re.sub(r'\n\[\s*\n(.*?)\n\]\s*\n', r'\n$$\n\1\n$$\n', text, flags=re.DOTALL)

    # Convert inline brackets to $$ (less common, but handle it)
    # Match [ ... ] that contains LaTeX-like content (formulas with backslashes, ^, _, etc.)
    text = re.sub(r'\[([^\[\]]*(?:[\\^_=]|\\[a-zA-Z]+)[^\[\]]*)\]', r'$$\1$$', text)

    # Convert \( ... \) to $ ... $ (inline math alternative delimiter)
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)

    # Convert \[ ... \] to $$ ... $$ (display math alternative delimiter)
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)

    return text


# ============================================================================
# State Definition
# ============================================================================

class AgentState(TypedDict):
    """State passed between nodes in the graph"""
    query: str
    messages: List[Any]
    context_files: List[Dict[str, Any]]  # Uploaded files (PDFs, images, etc.)
    available_tools: Dict[str, Dict[str, Any]]
    mcp_sessions: Dict[str, Any]

    # Global context (computed once)
    system_context: str  # Identity, date/time, guidelines - flows through all nodes

    # Planning
    needs_tools: bool
    requires_vision: bool  # Flag for vision model usage with uploaded images
    selected_tools: List[Dict[str, Any]]  # [{tool_name, arguments, reasoning}]

    # Execution
    tool_results: List[Dict[str, Any]]
    iteration: int
    max_iterations: int

    # Evaluation
    results_adequate: bool
    refinement_suggestion: Optional[str]

    # Final output
    final_answer: Optional[str]


# ============================================================================
# Node Functions
# ============================================================================

async def decide_tools_needed(state: AgentState) -> AgentState:
    """Decide if tools are needed to answer the question"""

    try:
        import chainlit as cl
    except:
        pass  # Chainlit not available in standalone mode

    # Extract state
    query = state["query"]
    system_context = state["system_context"]  # Already built!
    available_tools = state["available_tools"]
    messages = state.get("messages", [])
    context_files = state.get("context_files", [])

    # Build node-specific context
    tools_text = context_builders.build_tools_context_detailed(available_tools)
    history_context = context_builders.build_conversation_context(messages)
    files_context = context_builders.build_files_context_summary(context_files)

    # Debug: log available tools
    logger.info(f"Decision node sees {len(available_tools)} tools: {list(available_tools.keys())}")
    logger.info(f"Decision node sees {len(context_files)} uploaded files")

    # Build prompt using template
    prompt = prompts.prompt_decide_tools(
        system_context=system_context,
        query=query,
        tools_text=tools_text,
        history_context=history_context,
        files_context=files_context
    )

    # Debug: Log full prompt
    word_count = len(prompt.split())
    logger.info(f"[decide_tools] Prompt: {word_count} words, {len(prompt)} chars")
    logger.info(f"[decide_tools] FULL PROMPT:\n{'='*80}\n{prompt}\n{'='*80}")

    # Get model configuration
    config = NODE_MODELS["decide_tools"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # Handle reasoning models - extract JSON from response
        response_text = response.content
        if not response_text or response_text.strip() == "":
            logger.warning("Empty response from LLM, defaulting to needs_tools=True")
            state["needs_tools"] = True
            return state

        # Try to extract JSON (might be wrapped in text)
        import re
        json_match = re.search(r'\{[^{}]*\}', response_text)
        if json_match:
            decision = json.loads(json_match.group(0))
        else:
            decision = json.loads(response_text)

        state["needs_tools"] = decision.get("needs_tools", False)
        logger.info(f"Tool decision: {decision.get('needs_tools')}, Reasoning: {decision.get('reasoning')}")

        # Check if vision model is needed (uploaded images + question about them)
        has_images = any(f.get('type') == 'image' for f in context_files)
        if has_images and not state["needs_tools"]:
            # User uploaded images and doesn't need external tools
            # Use vision model to analyze the uploaded images
            state["requires_vision"] = True
            logger.info("Vision model will be used for uploaded image(s)")
        else:
            state["requires_vision"] = False

        # Emit to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                async with cl.Step(name="Decision: Tools Needed?", type="llm") as step:
                    reasoning = decision.get('reasoning', 'No reasoning')
                    step.output = f"**Decision:** {'Yes' if decision.get('needs_tools') else 'No'}\n\n**Reasoning:** {reasoning}"
        except:
            pass
    except Exception as e:
        logger.error(f"Tool decision failed: {e}")
        state["needs_tools"] = False

    return state


async def select_tools(state: AgentState) -> AgentState:
    """Select which tools to call and with what arguments"""

    # Extract state
    query = state["query"]
    system_context = state["system_context"]  # Already built!
    available_tools = state["available_tools"]
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)
    refinement = state.get("refinement_suggestion", "")

    # Add small delay on retries to avoid overwhelming Ollama
    if iteration > 0:
        import asyncio
        await asyncio.sleep(0.5)
        logger.debug(f"Retry attempt {iteration} after delay")

    # Safety check: if we're at or past max iterations, force empty to trigger stop
    if iteration >= max_iterations:
        logger.warning(f"Already at max iterations ({max_iterations}) in select_tools, forcing empty selection to stop")
        state["selected_tools"] = []
        return state

    # Build node-specific context
    tools_text = context_builders.build_tools_context_detailed(available_tools)
    history_context = context_builders.build_conversation_context(messages)  # ADD HISTORY
    refinement_context = context_builders.build_refinement_context(iteration, refinement)

    # Build prompt using template
    prompt = prompts.prompt_select_tools(
        system_context=system_context,
        query=query,
        tools_text=tools_text,
        history_context=history_context,  # PASS HISTORY
        refinement_context=refinement_context
    )

    # Debug: Log full prompt
    word_count = len(prompt.split())
    logger.info(f"[select_tools] Prompt: {word_count} words, {len(prompt)} chars")
    logger.info(f"[select_tools] FULL PROMPT:\n{'='*80}\n{prompt}\n{'='*80}")

    # Get model configuration
    config = NODE_MODELS["select_tools"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # Handle reasoning models - extract JSON from response
        response_text = response.content
        if not response_text or response_text.strip() == "":
            logger.error("Empty response from LLM for tool selection")
            state["selected_tools"] = []
            return state

        # Try to extract JSON (might be wrapped in text)
        import re
        json_match = re.search(r'\{.*"tools".*\}', response_text, re.DOTALL)
        if json_match:
            selection = json.loads(json_match.group(0))
        else:
            selection = json.loads(response_text)

        state["selected_tools"] = selection.get("tools", [])
        logger.info(f"Selected {len(state['selected_tools'])} tools")

        # Emit to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                async with cl.Step(name=f"Selected {len(state['selected_tools'])} Tool(s)", type="tool") as step:
                    if state['selected_tools']:
                        tools_info = "\n\n".join([
                            f"**{i+1}. {tc['tool_name']}**\n"
                            f"   Arguments: `{json.dumps(tc['arguments'])}`\n"
                            f"   Reason: {tc.get('reasoning', 'N/A')}"
                            for i, tc in enumerate(state['selected_tools'])
                        ])
                        step.output = tools_info
                    else:
                        step.output = "No tools selected"
        except:
            pass

    except Exception as e:
        logger.error(f"Tool selection failed: {e}")
        logger.error(f"Full LLM response: {response_text if 'response_text' in locals() else 'No response'}")
        state["selected_tools"] = []

    return state


async def call_tools(state: AgentState) -> AgentState:
    """Execute the selected tools"""

    selected_tools = state.get("selected_tools", [])
    mcp_sessions = state.get("mcp_sessions", {})
    tool_results = []

    for tool_call in selected_tools:
        tool_name = tool_call["tool_name"]
        arguments = tool_call["arguments"]

        logger.info(f"Calling {tool_name} with args: {arguments}")

        # Create Chainlit Step for this tool execution
        step_ctx = None
        try:
            import chainlit as cl
            if cl.context.session:
                step_ctx = cl.Step(name=f"Executing: {tool_name}", type="tool")
                await step_ctx.__aenter__()
                step_ctx.output = f"**Arguments:**\n```json\n{json.dumps(arguments, indent=2)}\n```"
        except:
            pass

        # Find which MCP session has this tool
        session = None
        for mcp_name, mcp_tuple in mcp_sessions.items():
            if isinstance(mcp_tuple, tuple):
                sess = mcp_tuple[0]
            else:
                sess = mcp_tuple

            try:
                tools_result = await sess.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                if tool_name in tool_names:
                    session = sess
                    break
            except Exception:
                continue

        if not session:
            result_entry = {
                "tool": tool_name,
                "success": False,
                "error": f"Tool '{tool_name}' not found",
                "data": None
            }
            tool_results.append(result_entry)

            # Update Step with error
            if step_ctx:
                try:
                    step_ctx.output += f"\n\n**Results:** Error: {result_entry['error']}"
                    await step_ctx.__aexit__(None, None, None)
                except:
                    pass
            continue

        # Call the tool
        try:
            result = await session.call_tool(tool_name, arguments)

            # Parse MCP result
            from mcp.types import TextContent
            if hasattr(result, 'content') and result.content:
                content = result.content[0]
                if isinstance(content, TextContent):
                    text = content.text or ""
                    try:
                        data = json.loads(text)

                        # Check if MCP server returned an error (even though it's valid JSON)
                        is_error = False
                        error_message = None

                        if isinstance(data, dict):
                            # Check for common error patterns
                            if data.get("ok") == False or "error" in data:
                                is_error = True
                                # Extract error message
                                if isinstance(data.get("error"), dict):
                                    error_message = data["error"].get("message", str(data["error"]))
                                elif isinstance(data.get("error"), str):
                                    error_message = data["error"]
                                else:
                                    error_message = str(data.get("error", "Unknown error"))

                        if is_error:
                            # Treat as failure
                            result_entry = {
                                "tool": tool_name,
                                "success": False,
                                "error": error_message,
                                "data": data  # Keep full data for debugging
                            }
                        else:
                            # Treat as success
                            result_entry = {
                                "tool": tool_name,
                                "success": True,
                                "data": data,
                                "error": None
                            }
                        tool_results.append(result_entry)

                        # Log full results to console
                        logger.info(f"Tool {tool_name} results: {json.dumps(data, indent=2)}")

                        # Update Step with result count or error
                        if step_ctx:
                            try:
                                if is_error:
                                    # Show error in step
                                    step_ctx.output += f"\n\n**Results:** ❌ Error: {error_message}"
                                else:
                                    # Count results based on data structure
                                    result_count = 0

                                    # Try different result structures
                                    if "top_results" in data:
                                        result_count = len(data.get("top_results", []))
                                    elif "data" in data and "results" in data["data"]:
                                        result_count = len(data["data"].get("results", []))
                                    elif "web" in data and "results" in data["web"]:
                                        result_count = len(data["web"].get("results", []))
                                    elif "results" in data:
                                        if isinstance(data["results"], list):
                                            result_count = len(data["results"])
                                        elif isinstance(data["results"], dict):
                                            result_count = data["results"].get("total", len(data["results"].get("hits", [])))
                                    elif "url" in data and "title" in data:
                                        result_count = 1

                                    if result_count > 0:
                                        step_ctx.output += f"\n\n**Results:** {result_count} items"
                                    else:
                                        step_ctx.output += f"\n\n**Results:** Success"
                                await step_ctx.__aexit__(None, None, None)
                            except:
                                pass

                    except json.JSONDecodeError:
                        # Likely an error message
                        result_entry = {
                            "tool": tool_name,
                            "success": False,
                            "error": text,
                            "data": None
                        }
                        tool_results.append(result_entry)

                        # Update Step with error
                        if step_ctx:
                            try:
                                step_ctx.output += f"\n\n**Results:** Error: {text}"
                                await step_ctx.__aexit__(None, None, None)
                            except:
                                pass
                else:
                    data = json.loads(str(content))
                    result_entry = {
                        "tool": tool_name,
                        "success": True,
                        "data": data,
                        "error": None
                    }
                    tool_results.append(result_entry)

                    # Log full results to console
                    logger.info(f"Tool {tool_name} results: {json.dumps(data, indent=2)}")

                    # Update Step with result count
                    if step_ctx:
                        try:
                            step_ctx.output += f"\n\n**Results:** Success"
                            await step_ctx.__aexit__(None, None, None)
                        except:
                            pass
            else:
                result_entry = {
                    "tool": tool_name,
                    "success": False,
                    "error": "Empty result",
                    "data": None
                }
                tool_results.append(result_entry)

                # Update Step with error
                if step_ctx:
                    try:
                        step_ctx.output += f"\n\n**Results:** Empty result"
                        await step_ctx.__aexit__(None, None, None)
                    except:
                        pass

        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            result_entry = {
                "tool": tool_name,
                "success": False,
                "error": str(e),
                "data": None
            }
            tool_results.append(result_entry)

            # Update Step with error
            if step_ctx:
                try:
                    step_ctx.output += f"\n\n**Results:** Error: {str(e)}"
                    await step_ctx.__aexit__(None, None, None)
                except:
                    pass

    state["tool_results"] = tool_results
    return state


async def evaluate_results(state: AgentState) -> AgentState:
    """Evaluate if tool results are adequate to answer the question"""

    # Extract state
    query = state["query"]
    tool_results = state.get("tool_results", [])
    selected_tools = state.get("selected_tools", [])
    max_iterations = state.get("max_iterations", 3)
    current_iteration = state.get("iteration", 0)

    # ONLY increment iteration counter if tools were actually executed
    # This prevents counting "decision only" cycles
    if len(tool_results) > 0:
        current_iteration = current_iteration + 1
        state["iteration"] = current_iteration
        logger.info(f"Tool execution iteration {current_iteration}/{max_iterations}")
    else:
        logger.warning(f"No tools were executed (empty selection). Not counting as iteration.")

    # Check if we have any successful results
    successful_results = [r for r in tool_results if r["success"]]

    # Also check if NO tools were selected (empty loop detection)
    if len(tool_results) == 0:
        logger.warning(f"No tools were executed. Treating as adequate (no tool use needed).")
        # If no tools were called, don't retry - just proceed
        state["results_adequate"] = True
        state["refinement_suggestion"] = None
        return state

    if not successful_results:
        # Build error summary to help LLM understand what went wrong
        failed_results = [r for r in tool_results if not r["success"]]
        error_summary = []
        for r in failed_results:
            error_msg = r.get("error", "Unknown error")
            error_summary.append(f"- {r['tool']}: {error_msg}")
        error_text = "\n".join(error_summary) if error_summary else "Unknown errors"

        # Force adequate if max iterations reached, otherwise retry
        if current_iteration >= max_iterations:
            logger.warning(f"All tool calls failed, but max iterations ({max_iterations}) reached")
            state["results_adequate"] = True
            state["refinement_suggestion"] = f"All tool calls failed:\n{error_text}"
        else:
            state["results_adequate"] = False
            state["refinement_suggestion"] = f"All tool calls failed with errors:\n{error_text}\n\nPlease adjust your tool parameters based on the error messages above."
        return state

    # Build results summary
    results_summary = []
    for r in successful_results:
        # With 65k context, use high limit but prevent complete context overflow
        # Limit per tool result to ~10k chars (allows multiple tool results)
        data_preview = json.dumps(r["data"], indent=2)[:10000]
        results_summary.append(f"Tool: {r['tool']}\nData: {data_preview}")

    summary_text = "\n\n".join(results_summary)

    # Build tool calls text (show what tools were called with what parameters)
    tool_calls_text = ""
    if selected_tools:
        tool_calls_lines = []
        for tc in selected_tools:
            tool_name = tc.get("tool_name", "unknown")
            arguments = tc.get("arguments", {})
            tool_calls_lines.append(f"- {tool_name} with arguments: {json.dumps(arguments)}")
        tool_calls_text = "\n".join(tool_calls_lines)

    # Build prompt using template
    system_context = state.get("system_context", "")
    prompt = prompts.prompt_evaluate_results(
        query=query,
        summary_text=summary_text,
        tool_calls_text=tool_calls_text,
        system_context=system_context
    )

    # Debug: Log full prompt
    word_count = len(prompt.split())
    logger.info(f"[evaluate_results] Prompt: {word_count} words, {len(prompt)} chars")
    logger.info(f"[evaluate_results] FULL PROMPT:\n{'='*80}\n{prompt}\n{'='*80}")

    # Get model configuration
    config = NODE_MODELS["evaluate_results"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # Handle reasoning models - extract JSON from response
        response_text = response.content
        if not response_text or response_text.strip() == "":
            logger.warning("Empty response from LLM for evaluation, proceeding")
            state["results_adequate"] = True
            return state

        # Try to extract JSON (might be wrapped in text)
        import re
        json_match = re.search(r'\{.*"adequate".*\}', response_text, re.DOTALL)
        if json_match:
            evaluation = json.loads(json_match.group(0))
        else:
            evaluation = json.loads(response_text)

        adequate = evaluation.get("adequate", True)
        reasoning = evaluation.get("reasoning", "N/A")

        # Use the current iteration that was already incremented at the start of this function
        current_iteration = state.get("iteration", 0)

        # Force adequate if we've completed max iterations
        if current_iteration >= max_iterations:
            adequate = True
            reasoning = f"Max iterations ({max_iterations}) reached. Proceeding with available information: {reasoning}"
            logger.info(f"Max iterations reached ({max_iterations}), proceeding to answer")

        state["results_adequate"] = adequate
        state["refinement_suggestion"] = evaluation.get("refinement", "")

        logger.info(f"Results adequate: {adequate}, Reasoning: {reasoning}")

        # Emit to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                async with cl.Step(name="Evaluation", type="llm") as step:
                    quality = "Adequate" if adequate else "Inadequate"
                    iter_info = f"Iteration {current_iteration}/{max_iterations}"
                    step.output = f"**Quality:** {quality}\n\n**Reasoning:** {reasoning}\n\n**Progress:** {iter_info}"
                    if not adequate and state.get('refinement_suggestion'):
                        step.output += f"\n\n**Refinement:** {state['refinement_suggestion']}"
        except:
            pass

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        state["results_adequate"] = True  # Proceed anyway

    return state


async def generate_answer_with_tools(state: AgentState) -> AgentState:
    """Generate final answer using tool results"""

    query = state["query"]
    tool_results = state.get("tool_results", [])
    context_files = state.get("context_files", [])

    # Build context from tool results and collect images/URLs
    context_parts = []
    source_references = []  # Track URLs and metadata for citations
    images_to_display = []  # Track images to insert

    # Add uploaded file context FIRST (before tool results)
    if context_files:
        context_parts.append("**UPLOADED FILES:**\n")
        for f in context_files:
            file_type = f.get('type', 'unknown')
            file_name = f.get('name', 'unknown')

            if file_type == 'image':
                # For images, note availability
                base64_data = f.get('base64', '')
                if base64_data:
                    context_parts.append(f"[FILE] Image: {file_name}\n[Image data available]")
                else:
                    context_parts.append(f"[FILE] Image: {file_name}\n[Image uploaded]")
            else:
                # For documents, include full preview (no truncation)
                preview = f.get('preview', '')
                if preview:
                    context_parts.append(f"[FILE] Document: {file_name}\n{preview}")
                else:
                    context_parts.append(f"[FILE] Document: {file_name}")
        context_parts.append("\n**TOOL RESULTS:**\n")

    for r in tool_results:
        if r["success"]:
            tool_name = r["tool"]
            data = r["data"]

            # Format based on tool type
            if "search_accelerator_knowledge" in tool_name:
                results = data.get("results", [])
                for i, item in enumerate(results):  # Process all results returned by tool
                    source_id = f"AccWiki-{i+1}"
                    url = item.get('url', 'N/A')
                    title = item.get('title', 'Unknown')

                    # Store reference metadata
                    source_references.append({
                        "id": source_id,
                        "title": title,
                        "url": url,
                        "type": "accwiki"
                    })

                    # Extract images if available
                    images = item.get('images', [])
                    if images:
                        for img in images[:]: 
                            images_to_display.append({
                                "source_id": source_id,
                                "url": img.get('url') or img.get('src'),
                                "caption": img.get('caption', f"Figure from {title}")
                            })

                    # Use pre-formatted context from MCP server (separation of concerns!)
                    formatted_context = item.get('formatted_context')
                    if formatted_context:
                        context_parts.append(f"[{source_id}]\n{formatted_context}")
                    else:
                        # Fallback if formatted_context not present (old server version)
                        logger.warning(f"AccWiki result missing formatted_context, using fallback")
                        content = item.get('content', '')
                        context_parts.append(f"[{source_id}] {title}\nContent: {content}\nURL: {url}")

            elif "elog" in tool_name.lower():
                # Handle both search_elog and get_elog_thread
                entries = []
                if "get_elog_thread" in tool_name:
                    # get_elog_thread: {"result": {"thread": [...]}}
                    entries = data.get("result", {}).get("thread", [])
                else:
                    # search_elog: {"results": {"hits": [...]}}
                    entries = data.get("results", {}).get("hits", [])

                for i, e in enumerate(entries):  # Process all entries returned by tool
                    source_id = f"ELOG-{i+1}"
                    elog_id = e.get('elog_id', 'N/A')
                    url = e.get('url', 'N/A')
                    title = e.get('title', 'N/A')
                    timestamp = e.get('timestamp', 'N/A')
                    author = e.get('author', 'N/A')
                    category = e.get('category', 'N/A')
                    system = e.get('system', 'N/A')
                    domain = e.get('domain', 'N/A')

                    # Parse timestamp for metadata: "Thu, 16 Oct 2025 21:13:14 +0200"
                    date_str = 'N/A'
                    time_str = 'N/A'
                    if timestamp and timestamp != 'N/A':
                        import re
                        date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', timestamp)
                        time_match = re.search(r'(\d{2}:\d{2}:\d{2})', timestamp)
                        if date_match:
                            date_str = date_match.group(1)
                        if time_match:
                            time_str = time_match.group(1)

                    # Store reference metadata - IMPORTANT: include elog_id for follow-up queries
                    source_references.append({
                        "id": source_id,
                        "elog_id": elog_id,
                        "title": title,
                        "url": url,
                        "date": date_str,
                        "time": time_str,
                        "author": author,
                        "category": category,
                        "system": system,
                        "domain": domain,
                        "type": "elog"
                    })

                    # Extract attachments/images for display
                    attachments = e.get('attachments', [])
                    for att in attachments:
                        img_url = att.get('url') if isinstance(att, dict) else str(att)
                        if img_url:
                            images_to_display.append({
                                "source_id": source_id,
                                "url": img_url,
                                "caption": f"Attachment from ELOG #{elog_id}"
                            })

                    # Use pre-formatted context from MCP server (separation of concerns!)
                    formatted_context = e.get('formatted_context')
                    if formatted_context:
                        context_parts.append(f"[{source_id}]\n{formatted_context}")
                    else:
                        # Fallback if formatted_context not present (old server version)
                        logger.warning(f"ELOG entry {elog_id} missing formatted_context, using fallback")
                        content = e.get('body_clean', '')
                        context_parts.append(f"[{source_id}] ELOG #{elog_id}: {title}\nContent: {content}\nURL: {url}")
            else:
                # Generic web search handler - works for all search tools
                # Try to extract results from various structures
                search_results = []

                if "top_results" in data:
                    # quick_search, structured_search: {"ok": true, "top_results": [...]}
                    search_results = data.get("top_results", [])
                elif "data" in data and "results" in data["data"]:
                    # web_search: {"ok": true, "data": {"results": [...]}}
                    search_results = data["data"]["results"]
                elif "web" in data and "results" in data["web"]:
                    # Brave MCP: {"web": {"results": [...]}}
                    search_results = data["web"]["results"]
                elif "results" in data and isinstance(data.get("results"), list):
                    # Generic results list
                    search_results = data["results"]
                elif "url" in data and "title" in data:
                    # Single result object
                    search_results = [data]

                # Extract knowledge_base if present (for quick_search/structured_search)
                knowledge_base_formatted = data.get('knowledge_base_formatted')
                if knowledge_base_formatted:
                    context_parts.append(f"[Knowledge Base]\n{knowledge_base_formatted}")

                if search_results:
                    # Process search results
                    for i, item in enumerate(search_results[:5]):
                        source_id = f"Web-{i+1}"
                        url = item.get('url', 'N/A')
                        title = item.get('title', 'Unknown')

                        # Store reference metadata
                        source_references.append({
                            "id": source_id,
                            "title": title,
                            "url": url,
                            "type": "web"
                        })

                        # Use pre-formatted context from MCP server (separation of concerns!)
                        formatted_context = item.get('formatted_context')
                        if formatted_context:
                            context_parts.append(f"[{source_id}]\n{formatted_context}")
                        else:
                            # Fallback if formatted_context not present (old server version)
                            logger.warning(f"Web result missing formatted_context, using fallback")
                            content = (item.get('snippet') or
                                      item.get('content') or
                                      item.get('description') or '')
                            context_parts.append(f"[{source_id}] {title}\nContent: {content}\nURL: {url}")
                else:
                    # Fallback for unrecognized data structure (limit to 5k per tool)
                    context_parts.append(f"[{tool_name}]\n{json.dumps(data, indent=2)[:5000]}")

    context_text = "\n\n---\n\n".join(context_parts)

    # Build reference list for the prompt
    references_text = "\n".join([
        f"- {ref['id']}: {ref['title']} - {ref['url']}"
        for ref in source_references
    ])

    # Build image information for the prompt
    images_text = ""
    if images_to_display:
        images_text = "\n\n**Available Images:**\n" + "\n".join([
            f"- Image from {img['source_id']}: {img['url']} (Caption: {img['caption']})"
            for img in images_to_display
        ])

    # Build prompt using template
    prompt = prompts.prompt_answer_with_tools(
        system_context=state["system_context"],  # Already built!
        query=query,
        context_text=context_text,
        references_text=references_text,
        images_text=images_text
    )

    # Debug: Log full prompt
    word_count = len(prompt.split())
    logger.info(f"[generate_answer_with_tools] Prompt: {word_count} words, {len(prompt)} chars")
    logger.info(f"[generate_answer_with_tools] FULL PROMPT:\n{'='*80}\n{prompt}\n{'='*80}")

    # Get model configuration
    config = NODE_MODELS["generate_answer_with_tools"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    try:
        logger.info(f"Generating final answer with tools... Context length: {word_count} words, {len(context_text)} chars, {len(source_references)} sources")
        logger.debug(f"Context preview (first 500 chars): {context_text[:500]}")

        # Stream response to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                msg = cl.Message(content="")
                await msg.send()

                # Stream tokens
                full_response = ""
                async for chunk in llm.astream([HumanMessage(content=prompt)]):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        await msg.stream_token(chunk.content)

                # Convert LaTeX delimiters and update the message
                full_response = convert_latex_delimiters(full_response)

                # Check if response is empty and generate fallback
                if not full_response or len(full_response.strip()) == 0:
                    logger.warning("LLM generated empty response, creating fallback answer")
                    fallback = "I apologize, but I was unable to generate a complete answer based on the available information. "
                    if source_references:
                        fallback += "However, I found these relevant sources:\n\n"
                        for ref in source_references:
                            fallback += f"- [{ref['title']}]({ref['url']})\n"
                    else:
                        fallback += "The search results did not contain sufficient information to answer your question directly. Please try rephrasing your question or provide more specific details."
                    full_response = fallback

                msg.content = full_response
                await msg.update()

                state["final_answer"] = full_response
                logger.info(f"Streamed final answer: {len(full_response)} chars")
            else:
                # Fallback for non-Chainlit context
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                state["final_answer"] = response.content
                logger.info(f"Generated final answer: {len(response.content)} chars")
        except:
            # Fallback to non-streaming
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            state["final_answer"] = response.content
            logger.info(f"Generated final answer (non-streamed): {len(response.content)} chars")

    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        state["final_answer"] = f"Error generating answer: {e}"

    return state


async def generate_answer_no_tools(state: AgentState) -> AgentState:
    """Generate answer without using tools"""

    # Extract state
    query = state["query"]
    system_context = state["system_context"]  # Already built!
    messages = state.get("messages", [])
    context_files = state.get("context_files", [])

    # Build node-specific context
    history_context = context_builders.build_conversation_context(messages)
    files_context = context_builders.build_files_context_full(context_files)

    # Build prompt using template
    prompt = prompts.prompt_answer_no_tools(
        system_context=system_context,
        query=query,
        history_context=history_context,
        files_context=files_context
    )

    # Debug: Log full prompt
    word_count = len(prompt.split())
    logger.info(f"[generate_answer_no_tools] Prompt: {word_count} words, {len(prompt)} chars")
    logger.info(f"[generate_answer_no_tools] FULL PROMPT:\n{'='*80}\n{prompt}\n{'='*80}")

    # Get model configuration
    config = NODE_MODELS["generate_answer_no_tools"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    try:
        # Stream response to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                msg = cl.Message(content="")
                await msg.send()

                # Stream tokens
                full_response = ""
                async for chunk in llm.astream([HumanMessage(content=prompt)]):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        await msg.stream_token(chunk.content)

                # Convert LaTeX delimiters and update the message
                full_response = convert_latex_delimiters(full_response)
                msg.content = full_response
                await msg.update()

                state["final_answer"] = full_response
                logger.info(f"Streamed answer (no tools): {len(full_response)} chars")
            else:
                # Fallback for non-Chainlit context
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                state["final_answer"] = response.content
        except:
            # Fallback to non-streaming
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            state["final_answer"] = response.content
    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        state["final_answer"] = f"Error generating answer: {e}"

    return state


async def generate_answer_with_vision(state: AgentState) -> AgentState:
    """Generate answer using vision model for uploaded image analysis"""

    # Extract state
    query = state["query"]
    system_context = state["system_context"]
    messages = state.get("messages", [])
    context_files = state.get("context_files", [])

    # Filter for images only
    image_files = [f for f in context_files if f.get('type') == 'image']

    if not image_files:
        logger.warning("Vision node called but no images found in context")
        state["final_answer"] = "No images were found to analyze."
        return state

    # Build node-specific context
    history_context = context_builders.build_conversation_context(messages)

    # Build prompt using template
    prompt_text = prompts.prompt_answer_with_vision(
        system_context=system_context,
        query=query,
        image_count=len(image_files),
        history_context=history_context
    )

    # Get vision model configuration
    config = NODE_MODELS["vision_answer"]
    llm = ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"]
    )

    # Build multimodal messages for Ollama
    # Format: [{"role": "user", "content": "text", "images": ["base64..."]}]
    images_base64 = []
    for img in image_files:
        base64_data = img.get('base64')
        if base64_data:
            images_base64.append(base64_data)
        else:
            logger.warning(f"Image {img.get('name')} has no base64 data")

    if not images_base64:
        logger.error("No valid base64 image data found")
        state["final_answer"] = "Unable to load image data for analysis."
        return state

    logger.info(f"Processing {len(images_base64)} image(s) with vision model {config['model']}")

    # Create message with images
    user_message = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}
              for img in images_base64]
        ]
    )

    try:
        # Stream response to Chainlit UI
        try:
            import chainlit as cl
            if cl.context.session:
                async with cl.Step(name=f"🔍 Analyzing {len(images_base64)} image(s)", type="llm") as step:
                    step.output = f"Using vision model: {config['model']}"

                msg = cl.Message(content="")
                await msg.send()

                # Stream tokens
                full_response = ""
                async for chunk in llm.astream([user_message]):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        await msg.stream_token(chunk.content)

                # Convert LaTeX delimiters and update the message
                full_response = convert_latex_delimiters(full_response)
                msg.content = full_response
                await msg.update()

                state["final_answer"] = full_response
                logger.info(f"Vision analysis complete: {len(full_response)} chars")
            else:
                # Fallback for non-Chainlit context
                response = await llm.ainvoke([user_message])
                state["final_answer"] = response.content
        except:
            # Fallback to non-streaming
            response = await llm.ainvoke([user_message])
            state["final_answer"] = response.content
    except Exception as e:
        logger.error(f"Vision answer generation failed: {e}")
        state["final_answer"] = f"Error analyzing image: {e}"

    return state


# ============================================================================
# Routing Functions
# ============================================================================

def route_after_decision(state: AgentState) -> Literal["select_tools", "answer_no_tools", "answer_with_vision"]:
    """Route based on whether tools or vision model are needed"""

    # Check vision first (uploaded images)
    if state.get("requires_vision", False):
        return "answer_with_vision"

    # Then check if external tools are needed
    if state.get("needs_tools", False):
        return "select_tools"

    return "answer_no_tools"


def route_after_evaluation(state: AgentState) -> Literal["select_tools", "answer_with_tools"]:
    """Route based on whether results are adequate"""

    # Always proceed if results are marked adequate
    if state.get("results_adequate", True):
        return "answer_with_tools"

    # Check if we've exceeded max iterations
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if iteration >= max_iterations:
        logger.warning(f"Max iterations ({max_iterations}) reached, proceeding to answer anyway")
        return "answer_with_tools"

    return "select_tools"


# ============================================================================
# Graph Construction
# ============================================================================

def create_agent_graph() -> StateGraph:
    """Create the LangGraph agent"""

    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("decide_tools", decide_tools_needed)
    workflow.add_node("select_tools", select_tools)
    workflow.add_node("call_tools", call_tools)
    workflow.add_node("evaluate", evaluate_results)
    workflow.add_node("answer_with_tools", generate_answer_with_tools)
    workflow.add_node("answer_no_tools", generate_answer_no_tools)
    workflow.add_node("answer_with_vision", generate_answer_with_vision)

    # Set entry point
    workflow.set_entry_point("decide_tools")

    # Add edges
    workflow.add_conditional_edges(
        "decide_tools",
        route_after_decision,
        {
            "select_tools": "select_tools",
            "answer_no_tools": "answer_no_tools",
            "answer_with_vision": "answer_with_vision"
        }
    )

    workflow.add_edge("select_tools", "call_tools")
    workflow.add_edge("call_tools", "evaluate")

    workflow.add_conditional_edges(
        "evaluate",
        route_after_evaluation,
        {
            "select_tools": "select_tools",  # Refine and retry
            "answer_with_tools": "answer_with_tools"
        }
    )

    workflow.add_edge("answer_with_tools", END)
    workflow.add_edge("answer_no_tools", END)
    workflow.add_edge("answer_with_vision", END)

    return workflow.compile()


# ============================================================================
# Main Interface
# ============================================================================

async def process_query(
    query: str,
    available_tools: Dict[str, Dict[str, Any]],
    mcp_sessions: Dict[str, Any],
    max_iterations: int = 3,
    message_history: List[Dict[str, str]] = None,
    context_files: List[Dict[str, Any]] = None
) -> str:
    """
    Process a user query with the autonomous agent.

    Args:
        query: User's question
        available_tools: Dict of tool_name -> tool_info
        mcp_sessions: Dict of MCP connection name -> (session, client)
        max_iterations: Maximum refinement attempts
        message_history: Optional conversation history [{"role": "user/assistant", "content": "..."}]
        context_files: Optional uploaded files with metadata (images, PDFs, etc.)

    Returns:
        Final answer string
    """

    # Build global system context ONCE (date/time, identity, guidelines)
    system_context = context_builders.build_system_context()
    logger.debug("Built global system context")

    # Create initial state
    initial_state: AgentState = {
        "query": query,
        "messages": message_history or [],
        "context_files": context_files or [],
        "available_tools": available_tools,
        "mcp_sessions": mcp_sessions,
        "system_context": system_context,  # Global context flows through all nodes
        "needs_tools": False,
        "requires_vision": False,
        "selected_tools": [],
        "tool_results": [],
        "iteration": 0,
        "max_iterations": max_iterations,
        "results_adequate": False,
        "refinement_suggestion": None,
        "final_answer": None
    }

    # Create and run graph with recursion limit
    graph = create_agent_graph()

    try:
        # Wrap execution in a "Thinking..." step that can be collapsed
        try:
            import chainlit as cl
            if cl.context.session:
                async with cl.Step(name="thinking...", type="tool") as thinking_step:
                    # Set recursion limit
                    config = {"recursion_limit": 30}
                    final_state = await graph.ainvoke(initial_state, config=config)

                    # Update thinking step with summary
                    iteration_count = final_state.get("iteration", 0)
                    tools_used = len(final_state.get("tool_results", []))
                    thinking_step.output = f"Completed in {iteration_count} iteration(s), used {tools_used} tool call(s)"

                    return final_state.get("final_answer", "No answer generated")
            else:
                # No Chainlit context
                config = {"recursion_limit": 30}
                final_state = await graph.ainvoke(initial_state, config=config)
                return final_state.get("final_answer", "No answer generated")
        except:
            # Fallback if Chainlit not available
            config = {"recursion_limit": 30}
            final_state = await graph.ainvoke(initial_state, config=config)
            return final_state.get("final_answer", "No answer generated")
    except Exception as e:
        logger.exception("Graph execution failed")
        return f"Error processing query: {e}"
