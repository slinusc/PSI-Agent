#!/usr/bin/env python3
"""
PSI Accelerator Knowledge Graph — MCP Server (SSE) + REST Facade

- MCP over HTTP/SSE for MCP-compatible clients (Open WebUI, etc.):
    • GET  /sse            -> server-sent events stream (server -> client)
    • POST /messages       -> MCP client -> server messages (mounted from SseServerTransport)

- REST API for scripts/humans:
    • POST /api/search
    • POST /api/related
    • GET  /healthz
    • GET  /metrics        -> simple in-memory counters

Design goals:
    - Shared core handlers (no duplication between MCP and REST)
    - Structured JSON errors with request_id
    - Per-request logging and timing
    - Minimal dependencies (Starlette + uvicorn)
"""

import os
import json
import time
import uuid
import logging
from typing import Any, Dict, List

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, PlainTextResponse
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

from accwiki_mcp.tools import search_accelerator_knowledge, get_related_content

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
)


class RequestIdFilter(logging.Filter):
    """Add default 'request_id' to all logs to avoid KeyError"""
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


logger = logging.getLogger("accelerator-mcp")
logger.addFilter(RequestIdFilter())

# -------------------------
# Globals / Singletons
# -------------------------
mcp_server = Server("psi-accelerator-knowledge-graph")
sse_transport = SseServerTransport("/messages")

# Simple in-memory metrics
METRICS = {
    "api_search_calls": 0,
    "api_related_calls": 0,
    "mcp_call_tool_calls": 0,
    "errors_total": 0,
}


# -------------------------
# Utilities
# -------------------------
def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def json_error(message: str, status_code: int = 400, request_id: str = "-") -> JSONResponse:
    METRICS["errors_total"] += 1
    payload = {
        "ok": False,
        "error": {
            "code": status_code,
            "message": message,
        },
        "request_id": request_id,
    }
    return JSONResponse(payload, status_code=status_code)


# -------------------------
# Core Handlers (shared by MCP & REST)
# -------------------------
def core_search(
    *,
    query: str,
    accelerator: str = "all",
    retriever: str = "dense",
    limit: int = 5,
    request_id: str = "-",
) -> Dict[str, Any]:
    """Wrapper that adds request_id and ok status to tool result."""
    result = search_accelerator_knowledge(
        query=query,
        accelerator=accelerator,
        retriever=retriever,
        limit=limit,
    )
    return {
        "ok": True,
        "request_id": request_id,
        **result,
    }


def core_related_content(
    *,
    article_id: str,
    relationship_types: List[str] = None,
    max_depth: int = 2,
    request_id: str = "-",
) -> Dict[str, Any]:
    """Wrapper that adds request_id and ok status to tool result."""
    result = get_related_content(
        article_id=article_id,
        relationship_types=relationship_types,
        max_depth=max_depth,
    )
    return {
        "ok": True,
        "request_id": request_id,
        **result,
    }


# -------------------------
# MCP Tool Registry
# -------------------------
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_accelerator_knowledge",
            description=(
                "Search the PSI accelerator knowledge graph for technical information. "
                "CRITICAL: If the user mentions a facility name (HIPA/ProScan/SLS/SwissFEL), "
                "you MUST extract it and use the 'accelerator' parameter. Do NOT include "
                "facility names in the query - use the accelerator filter instead. "
                "Example: User asks 'HIPA buncher problems' → query='buncher problems', accelerator='hipa'"
                "Use german language to query the knowledge graph, since the content is in german."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The search query WITHOUT facility names. Do NOT include accelerator names "
                            "(HIPA/ProScan/SLS/SwissFEL) in the query - use the accelerator parameter instead. "
                            "Example: 'Dosisleistungsmonitore Ausfall' NOT 'HIPA Dosisleistungsmonitore'"
                        ),
                    },
                    "accelerator": {
                        "type": "string",
                        "description": (
                            "REQUIRED: Facility filter. If user mentions HIPA/ProScan/SLS/SwissFEL, extract it here. "
                            "For general questions use 'all'. NEVER leave this empty."
                        ),
                        "enum": ["hipa", "proscan", "sls", "swissfel", "all"],
                        "default": "all",
                    },
                    "retriever": {
                        "type": "string",
                        "description": (
                            "Retrieval method: 'dense' for semantic vector search, 'sparse' for keyword/fulltext search, "
                            "'both' for hybrid search combining both methods"
                        ),
                        "enum": ["dense", "sparse", "both"],
                        "default": "dense",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query", "accelerator"],
            },
        ),
        Tool(
            name="get_related_content",
            description=(
                "Retrieve related content and context for a specific article in the knowledge graph. "
                "Use to explore relationships and find connected information."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "The unique identifier of the article",
                    },
                    "relationship_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific relationship types to follow (e.g., ['HAS_SECTION', 'RELATED_TO'])",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth for relationship traversal",
                        "default": 2,
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
                "required": ["article_id"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    METRICS["mcp_call_tool_calls"] += 1
    req_id = new_request_id()
    start = time.time()
    try:
        logger.info(f"MCP call_tool '{name}' started", extra={"request_id": req_id})
        if name == "search_accelerator_knowledge":
            resp = core_search(
                query=arguments["query"],
                accelerator=arguments.get("accelerator", "all"),
                retriever=arguments.get("retriever", "dense"),
                limit=int(arguments.get("limit", 5)),
                request_id=req_id,
            )
        elif name == "get_related_content":
            resp = core_related_content(
                article_id=arguments["article_id"],
                relationship_types=arguments.get("relationship_types"),
                max_depth=int(arguments.get("max_depth", 2)),
                request_id=req_id,
            )
        else:
            return [TextContent(type="text", text=json.dumps({
                "ok": False,
                "request_id": req_id,
                "error": {"code": 400, "message": f"Unknown tool: {name}"},
            }, ensure_ascii=False))]
        elapsed = (time.time() - start) * 1000.0
        logger.info(f"MCP call_tool '{name}' finished in {elapsed:.1f} ms", extra={"request_id": req_id})
        return [TextContent(type="text", text=json.dumps(resp, indent=2, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"MCP tool error: {e}", extra={"request_id": req_id})
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "request_id": req_id,
            "error": {"code": 500, "message": str(e)},
        }, ensure_ascii=False))]


# -------------------------
# HTTP/SSE Endpoints
# -------------------------
async def handle_sse(request: Request):
    """Handle SSE connection for MCP (server -> client stream)."""
    req_id = new_request_id()
    logger.info("SSE connect", extra={"request_id": req_id})
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )
    logger.info("SSE disconnect", extra={"request_id": req_id})
    return Response()


# -------------------------
# REST API Endpoints
# -------------------------
async def api_search(request: Request):
    METRICS["api_search_calls"] += 1
    req_id = new_request_id()

    try:
        payload = await request.json()
    except Exception:
        return json_error("Invalid JSON body", 400, req_id)

    query = payload.get("query")
    accelerator = payload.get("accelerator", "all")
    retriever = payload.get("retriever", "dense")
    limit = payload.get("limit", 5)

    if not isinstance(query, str) or not query.strip():
        return json_error("Field 'query' (non-empty string) is required.", 400, req_id)

    if retriever not in ("dense", "sparse", "both"):
        return json_error("Field 'retriever' must be one of: 'dense', 'sparse', 'both'.", 400, req_id)

    try:
        limit = int(limit)
        if not (1 <= limit <= 20):
            return json_error("Field 'limit' must be between 1 and 20.", 400, req_id)
    except Exception:
        return json_error("Field 'limit' must be an integer.", 400, req_id)

    start = time.time()
    try:
        resp = core_search(
            query=query.strip(),
            accelerator=accelerator,
            retriever=retriever,
            limit=limit,
            request_id=req_id,
        )
        elapsed = (time.time() - start) * 1000.0
        logger.info(
            f"REST /api/search {retriever} limit={limit} -> {resp['results_count']} results in {elapsed:.1f} ms",
            extra={"request_id": req_id}
        )
        return JSONResponse(resp, status_code=200)
    except Exception as e:
        logger.exception(f"/api/search error: {e}", extra={"request_id": req_id})
        return json_error(str(e), 500, req_id)


async def api_related(request: Request):
    METRICS["api_related_calls"] += 1
    req_id = new_request_id()

    try:
        payload = await request.json()
    except Exception:
        return json_error("Invalid JSON body", 400, req_id)

    article_id = payload.get("article_id")
    relationship_types = payload.get("relationship_types")
    max_depth = payload.get("max_depth", 2)

    if not isinstance(article_id, str) or not article_id.strip():
        return json_error("Field 'article_id' (non-empty string) is required.", 400, req_id)

    if relationship_types is not None and not isinstance(relationship_types, list):
        return json_error("Field 'relationship_types' must be a list of strings or omitted.", 400, req_id)

    try:
        max_depth = int(max_depth)
        if not (1 <= max_depth <= 5):
            return json_error("Field 'max_depth' must be between 1 and 5.", 400, req_id)
    except Exception:
        return json_error("Field 'max_depth' must be an integer.", 400, req_id)

    start = time.time()
    try:
        resp = core_related_content(
            article_id=article_id.strip(),
            relationship_types=relationship_types,
            max_depth=max_depth,
            request_id=req_id,
        )
        elapsed = (time.time() - start) * 1000.0
        logger.info(f"REST /api/related {article_id} -> ok in {elapsed:.1f} ms", extra={"request_id": req_id})
        return JSONResponse(resp, status_code=200)
    except Exception as e:
        logger.exception(f"/api/related error: {e}", extra={"request_id": req_id})
        return json_error(str(e), 500, req_id)


async def list_tools_rest(_: Request):
    tools = await list_tools()
    return JSONResponse([t.model_dump() for t in tools], status_code=200)


async def healthz(_: Request):
    return PlainTextResponse("ok\n", status_code=200)


async def metrics(_: Request):
    return JSONResponse({"ok": True, "metrics": METRICS}, status_code=200)


# -------------------------
# App & Routing
# -------------------------
routes = [
    # MCP transport endpoints
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Mount("/messages", app=sse_transport.handle_post_message),

    # REST API
    Route("/api/search", endpoint=api_search, methods=["POST"]),
    Route("/api/related", endpoint=api_related, methods=["POST"]),

    # Health & Metrics
    Route("/healthz", endpoint=healthz, methods=["GET"]),
    Route("/metrics", endpoint=metrics, methods=["GET"]),

    # Tool listing
    Route("/tools", endpoint=list_tools_rest, methods=["GET"]),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(routes=routes, middleware=middleware)


# -------------------------
# Startup / Main
# -------------------------
if __name__ == "__main__":
    import uvicorn

    # Initialize KG on boot (fail fast if issues)
    from accwiki_mcp.tools import get_kg
    try:
        get_kg()
        logger.info("MCP server ready", extra={"request_id": "-"})
    except Exception as e:
        logger.exception(f"Failed to initialize: {e}", extra={"request_id": "-"})
        raise

    # Run HTTP server
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")), log_level="info")
