#!/usr/bin/env python3
"""
SwissFEL ELOG — MCP Server (SSE) + REST Facade

MCP over HTTP/SSE for MCP-compatible clients (Open WebUI, etc.):
  • GET  /sse            -> server-sent events stream (server -> client)
  • POST /messages       -> MCP client -> server messages (mounted from SseServerTransport)

REST API for scripts/humans:
  • POST /api/search_elog
  • POST /api/thread
  • GET  /healthz
  • GET  /metrics

Design goals:
  - Shared core handlers (no duplication between MCP and REST)
  - Structured JSON errors with request_id
  - Per-request logging and timing
  - Minimal dependencies (Starlette + uvicorn)
"""

import os
import sys
import json
import time
import uuid
import logging
import warnings
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, PlainTextResponse
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

# -----------------------------------------------------------------------------
# Local imports (ensure current dir on sys.path)
# -----------------------------------------------------------------------------
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from elog_mcp.client import Logbook
from elog_mcp.tools import search_elog, get_elog_thread
from elog_mcp.constants import CATEGORIES, SYSTEMS, DOMAINS

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
class RequestIdFilter(logging.Filter):
    """Adds request_id to all log records, defaulting to '-' if not present"""
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True

# Add filter to root logger so ALL loggers inherit it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
)
root_logger = logging.getLogger()
root_logger.addFilter(RequestIdFilter())

logger = logging.getLogger("elog-mcp")

# -----------------------------------------------------------------------------
# Globals / Singletons
# -----------------------------------------------------------------------------
mcp_server = Server("swissfel-elog")
sse_transport = SseServerTransport("/messages")
logbook: Optional[Logbook] = None

METRICS = {
    "api_search_elog_calls": 0,
    "api_thread_calls": 0,
    "mcp_call_tool_calls": 0,
    "errors_total": 0,
}

def new_request_id() -> str:
    return uuid.uuid4().hex[:12]

def json_error(message: str, status_code: int = 400, request_id: str = "-") -> JSONResponse:
    METRICS["errors_total"] += 1
    return JSONResponse(
        {
            "ok": False,
            "error": {"code": status_code, "message": message},
            "request_id": request_id,
        },
        status_code=status_code,
    )

def get_logbook() -> Logbook:
    global logbook
    if logbook is None:
        elog_url = os.getenv("ELOG_URL", "https://elog-gfa.psi.ch/SwissFEL+commissioning/")
        logbook = Logbook(elog_url)
        logger.info(f"Logbook initialized: {elog_url}", extra={"request_id": "-"})
    return logbook

# -----------------------------------------------------------------------------
# Core handlers (shared by MCP & REST)
# -----------------------------------------------------------------------------
def core_search_elog(
    *,
    query: Optional[str],
    since: Optional[str],
    until: Optional[str],
    category: Optional[str],
    system: Optional[str],
    domain: Optional[str],
    max_results: int = 20,
    request_id: str = "-",
) -> Dict[str, Any]:
    lb = get_logbook()
    result = search_elog(
        logbook=lb,
        query=query,
        since=since,
        until=until,
        category=category,
        system=system,
        domain=domain,
        max_results=max_results,
    )
    return {"ok": True, "request_id": request_id, "results_count": len(result.get("hits", [])), "results": result}

def core_get_thread(
    *,
    message_id: int,
    include_replies: bool = True,
    include_parents: bool = True,
    request_id: str = "-",
) -> Dict[str, Any]:
    lb = get_logbook()
    result = get_elog_thread(
        logbook=lb,
        message_id=message_id,
        include_replies=include_replies,
        include_parents=include_parents,
    )
    return {"ok": True, "request_id": request_id, "result": result}

# -----------------------------------------------------------------------------
# MCP Tool Registry
# -----------------------------------------------------------------------------
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_elog",
            description=(
                "Search SwissFEL ELOG entries with semantic ranking. Supports single-term search, multi-term regex search (term1.*term2) "
                "time ranges, and attribute filters. Returns entries sorted by relevance (for text queries) or "
                "chronologically (for time-based queries)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text or regex (e.g., 'beam dump', 'RF.*fault'). Omit to search by filters/dates only.",
                    },
                    "since": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD). Optional.",
                    },
                    "until": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD). Optional.",
                    },
                    "category": {
                        "type": "string",
                        "description": f"Filter by category. Optional. Valid: {', '.join(CATEGORIES)}",
                        "enum": CATEGORIES,
                    },
                    "system": {
                        "type": "string",
                        "description": f"Filter by system. Optional. Valid: {', '.join(SYSTEMS)}",
                        "enum": SYSTEMS,
                    },
                    "domain": {
                        "type": "string",
                        "description": f"Filter by domain. Optional. Valid: {', '.join(DOMAINS)}",
                        "enum": DOMAINS,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return. Range: 1-100. Default: 20.",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
            },
        ),
        Tool(
            name="get_elog_thread",
            description=(
                "Get full conversation thread for an ELOG entry, including replies and parent messages. "
                "Useful for understanding incident context and follow-up."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "integer",
                        "description": "ELOG message ID (from search results as 'elog_id').",
                    },
                    "include_replies": {
                        "type": "boolean",
                        "description": "Include reply chain (descendants). Default: true.",
                        "default": True,
                    },
                    "include_parents": {
                        "type": "boolean",
                        "description": "Include parent chain (ancestors). Default: true.",
                        "default": True,
                    },
                },
                "required": ["message_id"],
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
        if name == "search_elog":
            resp = core_search_elog(
                query=arguments.get("query"),
                since=arguments.get("since"),
                until=arguments.get("until"),
                category=arguments.get("category"),
                system=arguments.get("system"),
                domain=arguments.get("domain"),
                max_results=int(arguments.get("max_results", 20)),
                request_id=req_id,
            )
        elif name == "get_elog_thread":
            mid = arguments["message_id"]
            resp = core_get_thread(
                message_id=int(mid),
                include_replies=bool(arguments.get("include_replies", True)),
                include_parents=bool(arguments.get("include_parents", True)),
                request_id=req_id,
            )
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"ok": False, "request_id": req_id, "error": {"code": 400, "message": f"Unknown tool: {name}"}},
                        ensure_ascii=False,
                    ),
                )
            ]
        elapsed = (time.time() - start) * 1000.0
        logger.info(f"MCP call_tool '{name}' finished in {elapsed:.1f} ms", extra={"request_id": req_id})
        return [TextContent(type="text", text=json.dumps(resp, indent=2, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"MCP tool error: {e}", extra={"request_id": req_id})
        return [
            TextContent(
                type="text",
                text=json.dumps({"ok": False, "request_id": req_id, "error": {"code": 500, "message": str(e)}}, ensure_ascii=False),
            )
        ]

# -----------------------------------------------------------------------------
# HTTP / SSE endpoints
# -----------------------------------------------------------------------------
async def handle_sse(request: Request):
    req_id = new_request_id()
    logger.info("SSE connect", extra={"request_id": req_id})
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())
    logger.info("SSE disconnect", extra={"request_id": req_id})
    return Response()

# -----------------------------------------------------------------------------
# REST API endpoints
# -----------------------------------------------------------------------------
async def api_search_elog(request: Request):
    METRICS["api_search_elog_calls"] += 1
    req_id = new_request_id()
    try:
        payload = await request.json()
    except Exception:
        return json_error("Invalid JSON body", 400, req_id)

    query = payload.get("query")
    since = payload.get("since")
    until = payload.get("until")
    category = payload.get("category")
    system = payload.get("system")
    domain = payload.get("domain")
    max_results = payload.get("max_results", 20)

    if category is not None and category not in CATEGORIES:
        return json_error(f"Invalid 'category'. Must be one of: {', '.join(CATEGORIES)}", 400, req_id)
    if system is not None and system not in SYSTEMS:
        return json_error(f"Invalid 'system'. Must be one of: {', '.join(SYSTEMS)}", 400, req_id)
    if domain is not None and domain not in DOMAINS:
        return json_error(f"Invalid 'domain'. Must be one of: {', '.join(DOMAINS)}", 400, req_id)

    try:
        max_results = int(max_results)
        if not (1 <= max_results <= 100):
            return json_error("Field 'max_results' must be between 1 and 100.", 400, req_id)
    except Exception:
        return json_error("Field 'max_results' must be an integer.", 400, req_id)

    start = time.time()
    try:
        resp = core_search_elog(
            query=query,
            since=since,
            until=until,
            category=category,
            system=system,
            domain=domain,
            max_results=max_results,
            request_id=req_id,
        )
        elapsed = (time.time() - start) * 1000.0
        logger.info(
            f"REST /api/search_elog -> {resp['results_count']} results in {elapsed:.1f} ms", extra={"request_id": req_id}
        )
        return JSONResponse(resp, status_code=200)
    except Exception as e:
        logger.exception(f"/api/search_elog error: {e}", extra={"request_id": req_id})
        return json_error(str(e), 500, req_id)

async def api_thread(request: Request):
    METRICS["api_thread_calls"] += 1
    req_id = new_request_id()
    try:
        payload = await request.json()
    except Exception:
        return json_error("Invalid JSON body", 400, req_id)

    message_id = payload.get("message_id")
    include_replies = bool(payload.get("include_replies", True))
    include_parents = bool(payload.get("include_parents", True))

    try:
        message_id = int(message_id)
    except Exception:
        return json_error("Field 'message_id' (integer) is required.", 400, req_id)

    start = time.time()
    try:
        resp = core_get_thread(
            message_id=message_id,
            include_replies=include_replies,
            include_parents=include_parents,
            request_id=req_id,
        )
        elapsed = (time.time() - start) * 1000.0
        logger.info(f"REST /api/thread id={message_id} -> ok in {elapsed:.1f} ms", extra={"request_id": req_id})
        return JSONResponse(resp, status_code=200)
    except Exception as e:
        logger.exception(f"/api/thread error: {e}", extra={"request_id": req_id})
        return json_error(str(e), 500, req_id)

async def list_tools_rest(_: Request):
    tools = await list_tools()  # reuse your MCP list_tools handler
    return JSONResponse([t.model_dump() for t in tools], status_code=200)

async def healthz(_: Request):
    return PlainTextResponse("ok\n", status_code=200)

async def metrics(_: Request):
    return JSONResponse({"ok\n": True, "metrics": METRICS}, status_code=200)

# -----------------------------------------------------------------------------
# App & routing
# -----------------------------------------------------------------------------
routes = [
    # MCP transport
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Mount("/messages", app=sse_transport.handle_post_message),

    # REST
    Route("/api/search_elog", endpoint=api_search_elog, methods=["POST"]),
    Route("/api/thread", endpoint=api_thread, methods=["POST"]),

    # Health & metrics
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

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    try:
        get_logbook()
        logger.info("ELOG MCP server ready", extra={"request_id": "-"})
    except Exception as e:
        logger.exception(f"Failed to initialize: {e}", extra={"request_id": "-"})
        raise

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8002")), log_level="info")


    # curl -X POST http://localhost:8002/api/thread "Content-Type: application/json" -d '{"message_id": 39084 }'
    # curl -X POST http://localhost:8002/api/search_elog "Content-Type: application/json" -d '{"query": "beam dump", "since": "2023-01-01", "max_results": 5 }'