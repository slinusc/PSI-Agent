"""
LLM-ready formatting for AccWiki search results.

Keeps formatting logic in the MCP server (interface layer) rather than
application code, following separation of concerns pattern.
"""

from typing import Dict, Any, List, Optional


def format_article_for_llm(article: Dict[str, Any]) -> str:
    """
    Format an AccWiki article as LLM-ready Markdown text.

    Args:
        article: Article dictionary with keys:
            - article_id: Unique identifier
            - title: Article title
            - url: Direct URL to article
            - context: Context path (e.g., "hipa:iw2-ip2")
            - section: Section title
            - content: Article text content
            - score: Relevance score
            - images: List of image dictionaries

    Returns:
        Markdown-formatted string ready for LLM consumption
    """
    article_id = article.get("article_id", "")
    title = article.get("title", "Untitled")
    url = article.get("url", "")
    context_path = article.get("context", "")
    section = article.get("section", "")
    content = article.get("content", "")
    score = article.get("score", 0.0)
    images = article.get("images", [])

    formatted = f"### {title}\n\n"
    formatted += f"**URL:** {url}\n"
    if context_path:
        formatted += f"**Context:** {context_path}\n"
    if section:
        formatted += f"**Section:** {section}\n"
    formatted += f"**Relevance:** {score}\n"
    formatted += f"**Article ID:** {article_id}\n\n"
    formatted += f"**Content:**\n{content}\n"

    if images:
        formatted += f"\n**Images ({len(images)} available):**\n"
        for img in images[:3]:  # Limit to first 3 images
            img_url = img.get('url', '')
            caption = img.get('caption', 'Figure')
            formatted += f"- [{caption}]({img_url})\n"

    return formatted


def to_figures(figs: Optional[List[dict]]) -> List[dict]:
    """
    Convert figure data to standardized format.

    Args:
        figs: List of figure dictionaries from knowledge graph

    Returns:
        List of standardized figure dictionaries with url, caption, type
    """
    out: List[dict] = []
    if not figs:
        return out
    for f in figs:
        if f and f.get("url"):
            out.append(
                {
                    "url": f["url"],
                    "caption": f.get("caption", ""),
                    "type": f.get("mime", ""),
                }
            )
    return out


def to_structured_result(r: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert raw knowledge graph result to structured format with LLM-ready context.

    Args:
        r: Raw result dictionary from knowledge graph query

    Returns:
        Structured result with formatted_context field
    """
    result = {
        "article_id": r.get("article_id", ""),
        "title": r.get("article_title", ""),
        "url": r.get("article_url", ""),
        "context": r.get("context_path", ""),
        "section": r.get("section_title", ""),
        "chunk_id": r.get("chunk_id", ""),
        "content": r.get("text", ""),
        "score": round(r.get("score", 0.0), 3),
        "images": to_figures(r.get("figures")),
    }
    # Add formatted context for LLM consumption
    result["formatted_context"] = format_article_for_llm(result)
    return result
