#!/usr/bin/env python3
"""
Simple query interface for PSI Accelerator Knowledge Graph.
Provides semantic search with dense/sparse/hybrid retrieval.
"""

import os
import sys
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict

from neo4j import GraphDatabase

from .embeddings import get_embedder

# Configuration
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

# Default embedding model
EMBEDDING_MODEL = "BAAI/bge-m3"
VECTOR_INDEX = "content_embeddings_bge_m3"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KnowledgeGraphQuery:
    """Query interface for the PSI Accelerator Knowledge Graph."""

    def __init__(self):
        """Initialize connection to Neo4j and load embedder."""
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        self.embedder = get_embedder(model_name=EMBEDDING_MODEL)
        logger.info(f"Connected to Neo4j at {NEO4J_URI}")

    def close(self):
        """Close database connection."""
        self.driver.close()

    def search(
        self,
        query: str,
        accelerator: Optional[str] = None,
        retriever: str = "dense",
        limit: int = 10,
        similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph.

        Args:
            query: Search query text
            accelerator: Optional filter (hipa, proscan, sls, swissfel)
            retriever: "dense", "sparse", or "both"
            limit: Max results
            similarity_threshold: Min similarity for dense search

        Returns:
            List of results with content, metadata, and scores
        """
        if retriever == "dense":
            return self._dense_search(query, accelerator, similarity_threshold, limit)
        elif retriever == "sparse":
            return self._sparse_search(query, accelerator, limit)
        elif retriever == "both":
            return self._hybrid_search(query, accelerator, similarity_threshold, limit)
        else:
            raise ValueError(f"Invalid retriever: {retriever}")

    def _dense_search(
        self,
        query: str,
        accelerator: Optional[str],
        similarity_threshold: float,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Vector similarity search."""
        # Encode query
        query_embedding = self.embedder.encode_query(query)
        if hasattr(query_embedding, 'tolist'):
            query_embedding = query_embedding.tolist()

        # Build Cypher query
        cypher = f"""
        CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $limit_mult, $query_emb)
        YIELD node AS content, score
        WHERE score >= $threshold
        MATCH (content)-[:PART_OF]->(article:Article)
        """

        if accelerator:
            cypher += "WHERE article.accelerator = $accelerator "

        cypher += """
        OPTIONAL MATCH (content)-[:HAS_FIGURE]->(fig:Figure)
        WITH content, article, score, collect(DISTINCT {
            url: fig.url,
            caption: fig.caption,
            mime: fig.mime
        })[0..2] AS figures
        RETURN
            content.chunk_id AS chunk_id,
            content.text AS text,
            content.section_title AS section_title,
            article.article_id AS article_id,
            article.title AS article_title,
            article.url AS article_url,
            article.accelerator AS accelerator,
            article.path_from_root AS context_path,
            figures,
            score
        ORDER BY score DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(
                cypher,
                query_emb=query_embedding,
                threshold=similarity_threshold,
                limit=limit,
                limit_mult=limit * 3,
                accelerator=accelerator
            )
            return [dict(record) for record in result]

    def _sparse_search(
        self,
        query: str,
        accelerator: Optional[str],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Fulltext (BM25) search."""
        import re
        # Escape Lucene special characters
        escaped_query = re.sub(r'[+\-&|!(){}\[\]^"~*?:\\/]', ' ', query)
        escaped_query = ' '.join(escaped_query.split())

        cypher = """
        CALL db.index.fulltext.queryNodes('content_fulltext', $query_text)
        YIELD node AS content, score
        MATCH (content)-[:PART_OF]->(article:Article)
        WHERE $accelerator IS NULL OR article.accelerator = $accelerator
        OPTIONAL MATCH (content)-[:HAS_FIGURE]->(fig:Figure)
        WITH content, article, score, collect(DISTINCT {
            url: fig.url,
            caption: fig.caption,
            mime: fig.mime
        })[0..2] AS figures
        RETURN
            content.chunk_id AS chunk_id,
            content.text AS text,
            content.section_title AS section_title,
            article.article_id AS article_id,
            article.title AS article_title,
            article.url AS article_url,
            article.accelerator AS accelerator,
            article.path_from_root AS context_path,
            figures,
            score
        ORDER BY score DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(
                cypher,
                query_text=escaped_query,
                accelerator=accelerator,
                limit=limit
            )
            return [dict(record) for record in result]

    def _hybrid_search(
        self,
        query: str,
        accelerator: Optional[str],
        similarity_threshold: float,
        limit: int,
        k: int = 50
    ) -> List[Dict[str, Any]]:
        """Hybrid search with RRF (Reciprocal Rank Fusion)."""
        # Get results from both retrievers
        dense_results = self._dense_search(query, accelerator, similarity_threshold, limit * 3)
        sparse_results = self._sparse_search(query, accelerator, limit * 3)

        # Calculate RRF scores
        rrf_scores = defaultdict(float)
        chunk_to_result = {}

        for rank, result in enumerate(dense_results, start=1):
            chunk_id = result['chunk_id']
            rrf_scores[chunk_id] += 1.0 / (k + rank)
            chunk_to_result[chunk_id] = result

        for rank, result in enumerate(sparse_results, start=1):
            chunk_id = result['chunk_id']
            rrf_scores[chunk_id] += 1.0 / (k + rank)
            if chunk_id not in chunk_to_result:
                chunk_to_result[chunk_id] = result

        # Sort by RRF score and return top results
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for chunk_id, rrf_score in sorted_chunks[:limit]:
            result = chunk_to_result[chunk_id].copy()
            result['score'] = rrf_score
            results.append(result)

        return results


    def get_related_content(
        self,
        article_id: str,
        relationship_types: Optional[List[str]] = ["REFERENCES"],
        max_depth: int = 2
    ) -> Dict[str, Any]:
        """
        Get related content for an article.

        Args:
            article_id: Article identifier
            relationship_types: Relationship types to follow
            max_depth: Traversal depth

        Returns:
            Dictionary with article info and related content
        """
        if relationship_types is None:
            relationship_types = ['REFERENCES', 'CONTAINS']

        rel_filter = '|'.join(relationship_types)

        cypher = f"""
        MATCH (article:Article {{article_id: $article_id}})
        OPTIONAL MATCH (article)<-[:PART_OF]-(content:Content)
        OPTIONAL MATCH path = (article)-[:{rel_filter}*1..{max_depth}]->(related:Article)
        OPTIONAL MATCH (related)<-[:PART_OF]-(rel_content:Content)

        RETURN
            article.title AS title,
            article.path_from_root AS context_path,
            article.accelerator AS accelerator,
            collect(DISTINCT {{
                text: content.text,
                section: content.section_title,
                chunk_id: content.chunk_id
            }}) AS main_content,
            collect(DISTINCT {{
                article_id: related.article_id,
                title: related.title,
                path: related.path_from_root
            }}) AS related_articles
        """

        with self.driver.session() as session:
            result = session.run(cypher, article_id=article_id)
            record = result.single()
            return dict(record) if record else {}



if __name__ == "__main__":
    import json
    kg_query = KnowledgeGraphQuery()
    try:
        query_text = (
            "Why does operating the buncher at MXZ3/4 in the HIPA facility pose a problem when the bunch "
            "length exceeds the linear region of the 506MHz sinusoidal voltage at currents above 2.2mA "
            "during production optics measurements?"
        )
        results = kg_query.search(query_text, accelerator="hipa", retriever="dense", limit=5)

        print(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        kg_query.close()
