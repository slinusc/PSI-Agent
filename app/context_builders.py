"""
Context Builders for LangGraph Agent

These functions build context strings that are used in prompts.
They are extracted from the node functions to avoid duplication and
make it easy to maintain consistent context across nodes.
"""

from datetime import datetime
from typing import List, Dict, Any


def build_system_context() -> str:
    """
    Build global system context that applies to all nodes.

    Includes:
    - Assistant identity and role
    - Current date and time
    - General guidelines for behavior
    - PSI-specific context (facilities)

    This string is computed once and passed through the entire graph.

    Returns:
        Formatted system context string
    """
    now = datetime.now()
    current_datetime = now.strftime("%A, %B %d, %Y at %H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    return f"""You are the PSI assistant at the Paul Scherrer Institute, a renowned research institute in Switzerland.

**Current Date and Time:** {current_datetime}
**Current Date (for calculations):** {current_date}

**Your Role:**
- Provide concise, accurate, and scientific answers
- Ground your responses in factual information
- Use proper technical terminology
- Cite sources when using external information
"""


def build_conversation_context(messages: List[Dict[str, Any]], max_messages: int = 10) -> str:
    """
    Build conversation history context from recent messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        max_messages: Maximum number of recent messages to include (default: 10 = 5 exchanges)
                     Increased from 6 to better support follow-up questions about retrieved information

    Returns:
        Formatted conversation context string, or empty string if no messages
    """
    if not messages:
        return ""

    recent_messages = messages[-max_messages:]
    history_lines = []
    for msg in recent_messages:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")  # No truncation - we have 65k context
        history_lines.append(f"{role}: {content}")

    history_text = "\n".join(history_lines)

    return f"""
**Recent Conversation:**
{history_text}
"""


def build_files_context_summary(context_files: List[Dict[str, Any]]) -> str:
    """
    Build file context summary (names and short previews only).
    Used for decision-making where full content isn't needed.

    Args:
        context_files: List of file dicts with 'type', 'name', 'preview' keys

    Returns:
        Formatted file context string, or empty string if no files
    """
    if not context_files:
        return ""

    files_lines = []
    for f in context_files:
        file_type = f.get('type', 'unknown')
        file_name = f.get('name', 'unknown')
        if file_type == 'image':
            files_lines.append(f"- Image: {file_name}")
        else:
            preview = f.get('preview', '')  # No truncation
            files_lines.append(f"- Document: {file_name} - {preview}")

    return f"""
**Uploaded Files:**
{chr(10).join(files_lines)}
"""


def build_files_context_full(context_files: List[Dict[str, Any]]) -> str:
    """
    Build full file context with complete content.
    Used for answer generation where full content is needed.

    Args:
        context_files: List of file dicts with 'type', 'name', 'preview', 'base64' keys

    Returns:
        Formatted file context string, or empty string if no files
    """
    if not context_files:
        return ""

    files_parts = []
    for f in context_files:
        file_type = f.get('type', 'unknown')
        file_name = f.get('name', 'unknown')

        if file_type == 'image':
            # For images, include base64 or indicate it's available
            base64_data = f.get('base64', '')
            if base64_data:
                files_parts.append(f"**Image: {file_name}**\n[Image data available for vision models]")
            else:
                files_parts.append(f"**Image: {file_name}**\n[Image uploaded but not accessible]")
        else:
            # For documents (PDFs, text files), include preview/content
            preview = f.get('preview', '')
            if preview:
                files_parts.append(f"**Document: {file_name}**\n{preview}")
            else:
                files_parts.append(f"**Document: {file_name}**\n[No preview available]")

    return f"""
**Uploaded Files:**
{chr(10).join(files_parts)}

"""


def build_tools_context_detailed(available_tools: Dict[str, Dict[str, Any]]) -> str:
    """
    Build detailed tool descriptions with full parameter schemas.
    Used for tool selection where the agent needs to know all parameters.

    Args:
        available_tools: Dict mapping tool names to tool info dicts

    Returns:
        Formatted detailed tool descriptions string
    """
    tool_descriptions = []
    for tool_name, tool_info in available_tools.items():
        desc = f"**{tool_name}**\n"
        desc += f"  Description: {tool_info.get('description', '')}\n"

        schema = tool_info.get("input_schema", {})
        if "properties" in schema:
            desc += "  Parameters:\n"
            for param_name, param_info in schema["properties"].items():
                param_type = param_info.get("type", "any")
                desc += f"    - {param_name} ({param_type})"

                # Show enum values (no truncation with 65k context)
                if "enum" in param_info:
                    desc += f" [options: {', '.join(param_info['enum'])}]"

                if param_name in schema.get("required", []):
                    desc += " [REQUIRED]"

                desc += "\n"

        tool_descriptions.append(desc)

    return "\n".join(tool_descriptions)


def build_refinement_context(iteration: int, refinement_suggestion: str) -> str:
    """
    Build refinement context for retry attempts.

    Args:
        iteration: Current iteration number (0-indexed)
        refinement_suggestion: Suggestion for how to improve

    Returns:
        Formatted refinement context string, or empty string if first attempt
    """
    if iteration == 0 or not refinement_suggestion:
        return ""

    return f"""
**Previous Attempt #{iteration} Failed**
Refinement suggestion: {refinement_suggestion}
Try a different approach or different tool arguments.
"""
