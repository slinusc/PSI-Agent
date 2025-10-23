"""
ELOG MCP Tools - Simplified API
================================

Simplified tool interface optimized for LLM/MCP tool use.
2 tools with minimal, flat parameters.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
import signal

from elog_mcp.client import Logbook
from elog_mcp.constants import validate_filter, CATEGORIES, SYSTEMS, DOMAINS
from elog_mcp.formatting import format_entry_for_llm
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

logger = logging.getLogger(__name__)

# Timeout configuration for ELOG operations
ELOG_READ_TIMEOUT = 10  # seconds per entry
ELOG_SEARCH_TIMEOUT = 30  # seconds for search operation


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _clean_html(text: str) -> str:
    """
    Remove HTML tags and entities from text content using BeautifulSoup.

    Uses BeautifulSoup for proper HTML parsing which handles:
    - HTML tags (preserving line breaks from <br>, <p>, etc.)
    - HTML entities (&nbsp;, &amp;, etc.)
    - HTML tables (converts to markdown tables)
    - Nested structures
    - Malformed HTML
    """
    if not text:
        return ""

    try:
        from bs4 import BeautifulSoup
        import re

        # Parse HTML
        soup = BeautifulSoup(text, 'html.parser')

        # Convert HTML tables to markdown tables
        for table in soup.find_all('table'):
            markdown_table = _html_table_to_markdown(table)
            table.replace_with(markdown_table)

        # Extract text preserving line breaks
        # Use newline as separator to preserve structure from <br>, <p>, <tr>, etc.
        clean = soup.get_text(separator='\n', strip=True)

        # Normalize excessive whitespace but preserve line breaks
        clean = re.sub(r' +', ' ', clean)  # Multiple spaces -> single space
        clean = re.sub(r'\n{3,}', '\n\n', clean)  # More than 2 newlines -> 2 newlines

        return clean.strip()
    except ImportError:
        # Fallback to regex if BeautifulSoup not available
        import re
        import html

        # Convert <br> and <p> to newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)

        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        clean = html.unescape(clean)
        # Normalize whitespace
        clean = re.sub(r' +', ' ', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean)

        return clean.strip()


def _html_table_to_markdown(table) -> str:
    """Convert HTML table to markdown table format"""
    rows = []
    for tr in table.find_all('tr'):
        cells = []
        for cell in tr.find_all(['td', 'th']):
            cells.append(cell.get_text(strip=True))
        if cells:
            rows.append('| ' + ' | '.join(cells) + ' |')

    if not rows:
        return ""

    # Add header separator if first row looks like header
    if len(rows) > 1 and table.find('th'):
        header_sep = '|' + '|'.join(['---'] * len(rows[0].split('|')[1:-1])) + '|'
        rows.insert(1, header_sep)

    return '\n' + '\n'.join(rows) + '\n'


def _read_and_parse(msg_id: int, logbook: Logbook, max_words: int = 500) -> Optional[Dict[str, Any]]:
    """
    Read and parse a single ELOG entry.

    Args:
        msg_id: ELOG message ID
        logbook: Logbook instance
        max_words: Maximum number of words to include in body_clean (default: 500)

    Returns:
        Dictionary with ELOG entry data, or None if read fails
    """
    try:
        message, attributes, attachments = logbook.read(msg_id)
        clean_body = _clean_html(message)

        # Limit body_clean to max_words to save tokens
        if clean_body:
            words = clean_body.split()
            if len(words) > max_words:
                clean_body = ' '.join(words[:max_words]) + '...'

        # Extract parent/reply relationship
        parent_id = attributes.get("In reply to")  # This entry is replying to parent_id
        reply_to = attributes.get("Reply to")      # This entry has a reply at reply_to

        return {
            "elog_id": msg_id,
            "title": attributes.get("Subject", attributes.get("Title", "")),
            "timestamp": attributes.get("Date", ""),
            "author": attributes.get("Author", ""),
            "category": attributes.get("Category", ""),
            "system": attributes.get("System", ""),
            "domain": attributes.get("Domain", ""),
            "section": attributes.get("Section", ""),
            "beamline": attributes.get("Beamline", ""),
            "effect": attributes.get("Effect", ""),
            "body_clean": clean_body,
            "attachments": [{"url": url, "filename": url.split('/')[-1]} for url in attachments],
            "url": f"{logbook._url}{msg_id}",
            "parent_id": int(parent_id) if parent_id else None,  # ID of message this replies to
            "reply_to": int(reply_to) if reply_to else None      # ID of message that replies to this
        }
    except Exception as e:
        # Use extra={'request_id': '-'} to avoid logging format errors in thread pool
        logger.warning(f"Failed to read msg_id {msg_id}: {e}", extra={'request_id': '-'})
        return None


def _bulk_read_parallel(msg_ids: List[int], logbook: Logbook, max_workers: int = 10) -> List[Dict[str, Any]]:
    """
    Read multiple ELOG entries in parallel with timeout protection.

    Entries that timeout or fail are skipped rather than blocking the entire fetch.
    """
    hits = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(_read_and_parse, msg_id, logbook): msg_id
            for msg_id in msg_ids
        }
        for future in as_completed(future_to_id, timeout=ELOG_READ_TIMEOUT * len(msg_ids)):
            msg_id = future_to_id[future]
            try:
                result = future.result(timeout=ELOG_READ_TIMEOUT)
                if result is not None:
                    hits.append(result)
            except FutureTimeoutError:
                logger.warning(f"Timeout reading msg_id {msg_id} after {ELOG_READ_TIMEOUT}s", extra={'request_id': '-'})
            except Exception as e:
                logger.warning(f"Error reading msg_id {msg_id}: {e}", extra={'request_id': '-'})
    return hits


def _parse_timestamp(timestamp_str: str) -> datetime:
    """Parse ELOG timestamp format: 'Wed, 17 Sep 2025 10:45:22 +0200'"""
    try:
        if not timestamp_str:
            return datetime.min
        # Remove day name and parse
        timestamp_str = ', '.join(timestamp_str.split(', ')[1:]) if ', ' in timestamp_str else timestamp_str
        return datetime.strptime(timestamp_str, "%d %b %Y %H:%M:%S %z").replace(tzinfo=None)
    except:
        return datetime.min


def _filter_by_date_range(hits: List[Dict[str, Any]], since: Optional[str], until: Optional[str]) -> List[Dict[str, Any]]:
    """Filter hits by date range."""
    if not since and not until:
        return hits

    # Parse date bounds
    since_dt = datetime.fromisoformat(since.replace('Z', '+00:00')) if since and 'T' in since else datetime.strptime(since, "%Y-%m-%d") if since else datetime.min
    until_dt = datetime.fromisoformat(until.replace('Z', '+00:00')) if until and 'T' in until else datetime.strptime(until, "%Y-%m-%d") if until else datetime.max
    if until:
        until_dt = until_dt.replace(hour=23, minute=59, second=59)  # Include entire end date

    filtered = []
    for hit in hits:
        hit_dt = _parse_timestamp(hit.get('timestamp', ''))
        if since_dt <= hit_dt <= until_dt:
            filtered.append(hit)

    return filtered


# ============================================================================
# TOOL 1: UNIFIED SEARCH
# ============================================================================

def search_elog(
    logbook: Logbook,
    query: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
    system: Optional[str] = None,
    domain: Optional[str] = None,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Search ELOG entries with flexible criteria.
    """
    # Validate inputs
    if category and not validate_filter("Category", category):
        raise ValueError(f"Invalid category: '{category}'. Must be one of: {CATEGORIES}")
    if system and not validate_filter("System", system):
        raise ValueError(f"Invalid system: '{system}'. Must be one of: {SYSTEMS}")
    if domain and not validate_filter("Domain", domain):
        raise ValueError(f"Invalid domain: '{domain}'. Must be one of: {DOMAINS}")
    if max_results < 1 or max_results > 100:
        raise ValueError(f"max_results must be between 1 and 100, got: {max_results}")
    if not query and not category and not system and not domain and not since:
        raise ValueError("Must provide at least one of: query, category, system, domain, or since")

    logger.info(f"[search_elog] query='{query}', since={since}, until={until}, "
                f"category={category}, system={system}, domain={domain}, max_results={max_results}",
                extra={'request_id': '-'})

    # Build filters
    filters = {}
    if category:
        filters["Category"] = category
    if system:
        filters["System"] = system
    if domain:
        filters["Domain"] = domain

    # Execute ELOG search
    try:
        if query and filters:
            msg_ids = logbook.search({**filters, "subtext": query}, n_results=max_results)
        elif query:
            msg_ids = logbook.search(query, n_results=max_results, scope="subtext")
        elif filters:
            msg_ids = logbook.search(filters, n_results=max_results)
        elif since or until:
            # Temporal-only search: fetch more entries because date filtering happens post-fetch
            # ELOG API doesn't support reliable date filtering, so we fetch extra and filter client-side
            fetch_count = max_results * 5  # Oversample 5x to ensure enough results after date filtering
            msg_ids = logbook.search({}, n_results=fetch_count)
        else:
            raise ValueError("No search criteria provided")
    except Exception as e:
        logger.error(f"ELOG search failed: {e}")
        return {"hits": [], "total_found": 0, "query_info": {"error": str(e)}, "aggregations": {}}

    hits = _bulk_read_parallel(msg_ids, logbook)

    # Apply date filtering (still trim to max_results after)
    if since or until:
        hits = _filter_by_date_range(hits, since, until)
        hits.sort(key=lambda h: _parse_timestamp(h.get('timestamp', '')), reverse=True)

    hits = hits[:max_results]

    # Add formatted_context to each hit for LLM consumption
    for hit in hits:
        hit['formatted_context'] = format_entry_for_llm(hit)

    # Build aggregations
    aggregations = {"category": {}, "system": {}, "domain": {}}
    for hit in hits:
        aggregations["category"][hit.get("category", "Unknown")] = aggregations["category"].get(hit.get("category", "Unknown"), 0) + 1
        aggregations["system"][hit.get("system", "Unknown")] = aggregations["system"].get(hit.get("system", "Unknown"), 0) + 1
        aggregations["domain"][hit.get("domain", "Unknown")] = aggregations["domain"].get(hit.get("domain", "Unknown"), 0) + 1

    return {
        "hits": hits,
        "total_found": len(msg_ids),
        "query_info": {
            "query": query,
            "since": since,
            "until": until,
            "category": category,
            "system": system,
            "domain": domain,
            "max_results": max_results
        },
        "aggregations": aggregations
    }



# ============================================================================
# TOOL 2: THREAD NAVIGATION
# ============================================================================

def get_elog_thread(
    logbook: Logbook,
    message_id: int,
    include_replies: bool = True,
    include_parents: bool = True
) -> Dict[str, Any]:
    """
    Get full conversation thread for an ELOG entry.

    Args:
        logbook: Logbook instance
        message_id: ELOG message ID
        include_replies: Include reply chain (descendants). Default: True.
        include_parents: Include parent chain (ancestors). Default: True.

    Returns:
        {
            "thread": [...],         # All messages in thread, chronologically ordered
            "root_message": {...},   # The root/original message
            "total_messages": int
        }
    """
    logger.info(f"[get_elog_thread] message_id={message_id}, replies={include_replies}, parents={include_parents}")

    thread = []

    # Get the original message
    try:
        original = _read_and_parse(message_id, logbook)
        if not original:
            return {"thread": [], "root_message": None, "total_messages": 0, "error": "Message not found"}
        thread.append(original)
    except Exception as e:
        logger.error(f"Failed to read message {message_id}: {e}")
        return {"thread": [], "root_message": None, "total_messages": 0, "error": str(e)}

    # Get parent chain (ancestors)
    if include_parents:
        try:
            parent_id = original.get("parent_id")
            while parent_id:
                parent = _read_and_parse(parent_id, logbook)
                if not parent:
                    break
                thread.insert(0, parent)  # Add to beginning
                parent_id = parent.get("parent_id")
        except Exception as e:
            logger.warning(f"Failed to traverse parent chain: {e}")

    # Get reply chain (descendants) - follow "Reply to" field iteratively
    if include_replies:
        try:
            visited = {message_id}
            to_check = [message_id]

            while to_check:
                current_id = to_check.pop(0)
                current = _read_and_parse(current_id, logbook)

                if not current:
                    continue

                # Check if this message has a reply
                reply_id = current.get("reply_to")
                if reply_id and reply_id not in visited:
                    visited.add(reply_id)
                    to_check.append(reply_id)
                    reply = _read_and_parse(reply_id, logbook)
                    if reply:
                        thread.append(reply)
        except Exception as e:
            logger.warning(f"Failed to get replies: {e}")

    # Sort by timestamp
    thread.sort(key=lambda m: _parse_timestamp(m.get('timestamp', '')))

    # Add formatted_context to each message for LLM consumption
    for message in thread:
        message['formatted_context'] = format_entry_for_llm(message)

    # Find root message
    root_message = thread[0] if thread else None

    return {
        "thread": thread,
        "root_message": root_message,
        "total_messages": len(thread)
    }


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    # Example usage
    elog_url = "https://elog-gfa.psi.ch/SwissFEL+commissioning/"
    logbook = Logbook(elog_url)

    # Search example
    results = search_elog(
        logbook=logbook,
        query="beam.*dump",
        since="2025-01-01",
        until="2025-12-31",
        max_results=5
    )
    print(f"Search found {results['total_found']} entries, returning {len(results['hits'])}:")
    for hit in results['hits']:
        print(f"- [{hit['timestamp']}] {hit['title']} text: {hit['body_clean'][:50]} (ID: {hit['elog_id']})")

    # Thread example
    thread_result = get_elog_thread(logbook=logbook, message_id=39084, include_replies=True, include_parents=True)
    print(f"Thread has {thread_result['total_messages']} messages:")
    for msg in thread_result['thread']:
        print(f"- [{msg['timestamp']}] {msg['title']} (ID: {msg['elog_id']})")
