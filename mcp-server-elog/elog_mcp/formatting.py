"""
Formatting utilities for ELOG entries
======================================

Functions to format ELOG entries as LLM-ready Markdown text.
"""

from datetime import datetime
from typing import Dict, Any


def format_entry_for_llm(entry: Dict[str, Any]) -> str:
    """
    Format an ELOG entry as LLM-ready Markdown text.

    This is the canonical formatting for ELOG entries - keeps formatting logic
    in the MCP server (interface layer) rather than in application code.

    Args:
        entry: Dictionary with ELOG entry data (from _read_and_parse)

    Returns:
        Markdown-formatted string ready for LLM consumption
    """
    elog_id = entry.get('elog_id', 'N/A')
    title = entry.get('title', 'Untitled')
    timestamp = entry.get('timestamp', '')
    author = entry.get('author', 'Unknown')
    category = entry.get('category', 'N/A')
    system = entry.get('system', 'N/A')
    domain = entry.get('domain', 'N/A')
    effect = entry.get('effect', 'N/A')
    body_clean = entry.get('body_clean', '')
    attachments = entry.get('attachments', [])
    url = entry.get('url', '')

    # Parse timestamp
    date_str = 'N/A'
    time_str = 'N/A'
    try:
        if timestamp:
            # ELOG format: "Wed, 17 Sep 2025 10:45:22 +0200"
            # Remove day name and parse
            timestamp_clean = ', '.join(timestamp.split(', ')[1:]) if ', ' in timestamp else timestamp
            # Try with timezone
            try:
                dt = datetime.strptime(timestamp_clean, '%d %b %Y %H:%M:%S %z')
            except:
                # Fallback: try without timezone
                dt = datetime.strptime(timestamp_clean.rsplit(' ', 1)[0], '%d %b %Y %H:%M:%S')
            date_str = dt.strftime('%Y-%m-%d')
            time_str = dt.strftime('%H:%M:%S')
    except Exception as e:
        # Keep as N/A if parsing fails
        pass

    # Build markdown formatted context
    formatted = f"### ELOG Entry #{elog_id}: {title}\n\n"
    formatted += f"**Date/Time:** {date_str} at {time_str}\n"
    formatted += f"**Author:** {author}\n"
    formatted += f"**Category:** {category}\n"
    formatted += f"**System:** {system} | **Domain:** {domain}\n"
    formatted += f"**Effect:** {effect}\n"
    formatted += f"**Link:** [elog-gfa.psi.ch/{elog_id}]({url})\n\n"
    formatted += f"**Content:**\n{body_clean}\n"

    # Add attachments if present
    if attachments:
        formatted += f"\n**Attachments ({len(attachments)} file(s)):**\n"
        for att in attachments:
            att_url = att.get('url', '') if isinstance(att, dict) else str(att)
            att_name = att.get('filename', att_url.split('/')[-1]) if isinstance(att, dict) else att_url.split('/')[-1]
            formatted += f"- [{att_name}]({att_url})\n"

    return formatted
