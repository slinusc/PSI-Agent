"""
AccWiki MCP Tools - Core search and related content functionality.

Provides two main tools:
1. search_accelerator_knowledge - Search the knowledge graph
2. get_related_content - Explore article relationships

These are pure functions that take parameters and return dictionaries,
making them easy to test and reuse outside of MCP protocol.
"""

import logging
from typing import Dict, Any, List, Optional

from accwiki_mcp.knowledge_graph.query import KnowledgeGraphQuery
from accwiki_mcp.formatting import to_structured_result

logger = logging.getLogger(__name__)

# Global singleton (lazy-loaded)
_kg_instance: Optional[KnowledgeGraphQuery] = None


def get_kg() -> KnowledgeGraphQuery:
    """Get or create the KnowledgeGraphQuery singleton."""
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraphQuery()
        logger.info("Knowledge Graph initialized", extra={"request_id": "-"})
    return _kg_instance


def search_accelerator_knowledge(
    query: str,
    accelerator: Optional[str] = None,
    retriever: str = "dense",
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Search the PSI Accelerator Knowledge Graph.

    Args:
        query: Search query (WITHOUT facility names - use accelerator param)
        accelerator: Facility filter ("hipa"|"proscan"|"sls"|"swissfel"|None for all)
        retriever: Retrieval method ("dense"|"sparse"|"both")
        limit: Maximum number of results (1-20)

    Returns:
        Dictionary with:
            - results: List of search results
            - results_count: Number of results returned
            - query: Original query
            - accelerator: Facility filter used
            - retriever: Retrieval method used
    """
    # Normalize accelerator param: treat "all"/empty/null as None
    if accelerator in ("", "all", "null", "None"):
        accelerator = None

    kg_instance = get_kg()
    results = kg_instance.search(
        query=query,
        accelerator=accelerator,
        retriever=retriever,
        limit=limit,
    )

    structured = [to_structured_result(r) for r in results]

    return {
        "query": query,
        "accelerator": accelerator,
        "retriever": retriever,
        "results_count": len(structured),
        "results": structured,
    }


def get_related_content(
    article_id: str,
    relationship_types: Optional[List[str]] = None,
    max_depth: int = 2,
) -> Dict[str, Any]:
    """
    Get related content for a specific article in the knowledge graph.

    Args:
        article_id: Unique article identifier (from search results)
        relationship_types: Specific relationship types to follow (e.g., ["HAS_SECTION", "RELATED_TO"])
        max_depth: Maximum depth for relationship traversal (1-5)

    Returns:
        Dictionary with:
            - article_id: Original article ID
            - max_depth: Depth used for traversal
            - result: Related content data from knowledge graph
    """
    kg_instance = get_kg()
    result = kg_instance.get_related_content(
        article_id=article_id,
        relationship_types=relationship_types,
        max_depth=max_depth,
    )

    return {
        "article_id": article_id,
        "max_depth": max_depth,
        "result": result,
    }
