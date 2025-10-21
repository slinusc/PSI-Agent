import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chainlit as cl
from chainlit import input_widget
from chainlit.data import BaseDataLayer
from chainlit.callbacks import data_layer as register_data_layer
from dotenv import load_dotenv
from ollama import AsyncClient
from pdf_processor import extract_pdf_text_safe
from graph_nodes import process_query as langgraph_process_query

try:
    import httpx
except ImportError:  # pragma: no cover - handled at runtime
    httpx = None


load_dotenv()

LOG_DIR = Path(os.getenv("CHAINLIT_LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=os.getenv("APP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "chainlit_app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("psi.chainlit")

DB_PATH = Path(os.getenv("CHAINLIT_DB_PATH", "chainlit.db"))
UPLOADS_DIR = Path(os.getenv("CHAINLIT_UPLOAD_DIR", "data/uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:20b-65k")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")

MODEL_OPTIONS = [m.strip() for m in os.getenv("OLLAMA_MODELS", DEFAULT_MODEL).split(",") if m.strip()]
HISTORY_MESSAGE_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "40"))
MAX_DOC_PREVIEW_CHARS = int(os.getenv("CONTEXT_PREVIEW_CHARS", "2000"))

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".log",
    ".ini",
    ".cfg",
}

DEFAULT_SYSTEM_PROMPT = """You are the PSI assistant. Provide concise, factual answers.

You have access to MCP tools for accessing internal information sources:
{mcp_tools_list}

When tool information, documents, or images are supplied, ground your answers in that material and cite sources clearly.

If you call tools, explain the results in plain language.

If information is missing, ask clarifying questions before assuming.

You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$
[expression]
$$' for standalone cases."""


def build_system_prompt_with_tools(base_prompt: str, mcp_tools: Dict[str, List[Dict]]) -> str:
    """Build system prompt with dynamically listed MCP tools"""

    if not mcp_tools:
        # No tools available, return base prompt without tool list
        return base_prompt.replace("\n{mcp_tools_list}\n", "")

    # Build tool list
    tool_lines = []
    for mcp_name, tools in mcp_tools.items():
        for tool in tools:
            tool_name = tool.get("name", "unknown")
            tool_desc = tool.get("description", "No description")
            # Truncate long descriptions
            if len(tool_desc) > 150:
                tool_desc = tool_desc[:147] + "..."
            tool_lines.append(f"- {tool_name}: {tool_desc}")

    tools_text = "\n".join(tool_lines)
    return base_prompt.replace("{mcp_tools_list}", tools_text)


def current_timestamp() -> str:
    return datetime.utcnow().isoformat()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(candidate: str, stored_hash: str) -> bool:
    return hash_password(candidate) == stored_hash


def default_settings() -> Dict[str, Any]:
    return {
        "model": DEFAULT_MODEL,
        "temperature": 0.2,
        "system_prompt": DEFAULT_SYSTEM_PROMPT.strip(),
        "use_tools": True,
    }


@dataclass
class ChatSessionState:
    messages: List[Dict[str, Any]] = field(default_factory=list)
    context_files: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=default_settings)


class SQLiteDataLayer(BaseDataLayer):
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    name TEXT,
                    created_at TIMESTAMP,
                    metadata TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS steps (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    type TEXT,
                    name TEXT,
                    output TEXT,
                    created_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (thread_id) REFERENCES threads (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS context_files (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    step_id TEXT,
                    name TEXT,
                    path TEXT,
                    type TEXT,
                    mime_type TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    step_id TEXT,
                    user_id TEXT,
                    rating INTEGER,
                    comment TEXT,
                    created_at TIMESTAMP,
                    metadata TEXT
                )
                """
            )
            self._ensure_column(cursor, "threads", "metadata", "TEXT")
            self._ensure_column(cursor, "steps", "metadata", "TEXT")
            conn.commit()

    async def _run(self, func, *args):
        return await asyncio.to_thread(func, *args)

    def _serialize_metadata(self, payload: Optional[Dict[str, Any]]) -> str:
        return json.dumps(payload or {}, ensure_ascii=False)

    async def create_step(self, step_dict: Dict[str, Any]):
        logger.debug("Persisting step: %s", step_dict.get("id"))
        def _create_step():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO steps (id, thread_id, type, name, output, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step_dict.get("id"),
                        step_dict.get("threadId"),
                        step_dict.get("type"),
                        step_dict.get("name"),
                        step_dict.get("output"),
                        datetime.utcnow(),
                        self._serialize_metadata(step_dict.get("metadata")),
                    ),
                )
                conn.commit()

        try:
            await self._run(_create_step)
        except Exception as exc:
            logger.error("Failed to create step %s: %s", step_dict.get("id"), exc)
            raise

    async def get_thread(self, thread_id: str):
        def _get_thread():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM threads WHERE id = ?", (thread_id,))
                thread_row = cursor.fetchone()
                if not thread_row:
                    logger.warning("Thread %s not found in database", thread_id)
                    return None
                logger.debug("Found thread %s: %s", thread_id, thread_row[2])
                cursor.execute(
                    "SELECT * FROM steps WHERE thread_id = ? ORDER BY created_at",
                    (thread_id,),
                )
                steps = cursor.fetchall()

                # Get elements for this thread
                cursor.execute(
                    "SELECT id, thread_id, step_id, name, path, type, mime_type, metadata, created_at FROM context_files WHERE thread_id = ? ORDER BY created_at",
                    (thread_id,),
                )
                elements_raw = cursor.fetchall()

                def get_element_type(mime_type: str, stored_type: str) -> str:
                    """Determine Chainlit element type from mime type."""
                    if not mime_type:
                        return "file"
                    if mime_type.startswith("image/"):
                        return "image"
                    if mime_type == "application/pdf":
                        return "pdf"
                    if mime_type.startswith("audio/"):
                        return "audio"
                    if mime_type.startswith("video/"):
                        return "video"
                    return "file"

                user_id = thread_row[1]
                elements = []
                for e in elements_raw:
                    element_type = get_element_type(e[6], e[5])  # mime_type, type
                    file_path = Path(e[4])  # path column

                    # Read file content for inline display
                    url = None
                    if file_path.exists():
                        # For images, we can use data URL with base64
                        if element_type == "image":
                            try:
                                content = file_path.read_bytes()
                                b64 = base64.b64encode(content).decode('utf-8')
                                url = f"data:{e[6]};base64,{b64}"
                            except Exception as ex:
                                logger.warning("Failed to read image %s: %s", file_path, ex)

                    elements.append({
                        "id": e[0],
                        "threadId": e[1],
                        "forId": e[2],
                        "name": e[3],
                        "url": url,  # Use data URL for images
                        "display": "inline",
                        "type": element_type,
                        "mime": e[6],
                        "objectKey": e[4],
                    })

                return {
                    "id": thread_row[0],
                    "userId": user_id,
                    "userIdentifier": user_id,  # Required by Chainlit
                    "name": thread_row[2],
                    "createdAt": thread_row[3],
                    "metadata": json.loads(thread_row[4] or "{}"),
                    "tags": [],
                    "elements": elements,
                    "steps": [
                        {
                            "id": s[0],
                            "threadId": s[1],
                            "type": s[2],
                            "name": s[3],
                            "output": s[4],
                            "createdAt": s[5],
                            "metadata": json.loads(s[6] or "{}"),
                        }
                        for s in steps
                    ],
                }

        return await self._run(_get_thread)

    async def list_threads(self, pagination: "cl.types.Pagination", filters: "cl.types.ThreadFilter"):
        from chainlit.types import PaginatedResponse, PageInfo

        def _list_threads():
            with self._connect() as conn:
                cursor = conn.cursor()

                # Build query based on filters
                query = "SELECT * FROM threads WHERE 1=1"
                params = []

                if filters.userId:
                    query += " AND user_id = ?"
                    params.append(filters.userId)

                if filters.search:
                    query += " AND name LIKE ?"
                    params.append(f"%{filters.search}%")

                query += " ORDER BY created_at DESC"

                # Apply pagination
                limit = pagination.first + 1  # Get one extra to check if there's a next page
                if pagination.cursor:
                    query += " AND created_at < ?"
                    params.append(pagination.cursor)

                query += f" LIMIT {limit}"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                # Check if there's a next page
                has_next_page = len(rows) > pagination.first
                if has_next_page:
                    rows = rows[:-1]  # Remove the extra row

                threads = [
                    {
                        "id": row[0],
                        "userId": row[1],
                        "userIdentifier": row[1],  # Required by Chainlit
                        "name": row[2],
                        "createdAt": row[3],
                        "metadata": json.loads(row[4] or "{}"),
                        "tags": [],
                        "steps": [],
                        "elements": [],
                    }
                    for row in rows
                ]

                # Build page info
                start_cursor = threads[0]["createdAt"] if threads else None
                end_cursor = threads[-1]["createdAt"] if threads else None

                return PaginatedResponse(
                    pageInfo=PageInfo(
                        hasNextPage=has_next_page,
                        startCursor=start_cursor,
                        endCursor=end_cursor,
                    ),
                    data=threads,
                )

        return await self._run(_list_threads)

    async def create_thread(self, thread_dict: Dict[str, Any]):
        def _create_thread():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO threads (id, user_id, name, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        thread_dict.get("id"),
                        thread_dict.get("userId"),
                        thread_dict.get("name", "New Chat"),
                        datetime.utcnow(),
                        self._serialize_metadata(thread_dict.get("metadata")),
                    ),
                )
                conn.commit()

        await self._run(_create_thread)

    async def delete_thread(self, thread_id: str):
        def _delete_thread():
            with self._connect() as conn:
                cursor = conn.cursor()

                # Get all file paths before deleting records
                cursor.execute("SELECT path FROM context_files WHERE thread_id = ?", (thread_id,))
                file_paths = [row[0] for row in cursor.fetchall()]

                # Delete database records
                cursor.execute("DELETE FROM context_files WHERE thread_id = ?", (thread_id,))
                cursor.execute("DELETE FROM steps WHERE thread_id = ?", (thread_id,))
                cursor.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
                conn.commit()

                # Delete actual files and directory
                for file_path in file_paths:
                    try:
                        p = Path(file_path)
                        if p.exists():
                            p.unlink()
                            logger.info("Deleted file: %s", file_path)
                    except Exception as exc:
                        logger.warning("Failed to delete file %s: %s", file_path, exc)

                # Try to remove the thread's upload directory if empty
                thread_dir = UPLOADS_DIR / thread_id
                if thread_dir.exists():
                    try:
                        thread_dir.rmdir()  # Only works if directory is empty
                        logger.info("Deleted empty directory: %s", thread_dir)
                    except OSError:
                        pass  # Directory not empty or other error, ignore

        await self._run(_delete_thread)

    async def update_thread(
        self,
        thread_id: str,
        name: str = None,
        user_id: str = None,
        metadata: dict = None,
        tags: list = None,
    ):
        def _update_thread():
            with self._connect() as conn:
                cursor = conn.cursor()
                if name:
                    cursor.execute("UPDATE threads SET name = ? WHERE id = ?", (name, thread_id))
                if metadata:
                    cursor.execute(
                        "UPDATE threads SET metadata = ? WHERE id = ?",
                        (self._serialize_metadata(metadata), thread_id),
                    )
                conn.commit()

        await self._run(_update_thread)

    async def delete_step(self, step_id: str):
        def _delete_step():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM steps WHERE id = ?", (step_id,))
                conn.commit()

        await self._run(_delete_step)

    async def update_step(self, step_dict: Dict[str, Any]):
        await self.create_step(step_dict)

    async def get_thread_author(self, thread_id: str):
        def _get_author():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM threads WHERE id = ?", (thread_id,))
                result = cursor.fetchone()
                return result[0] if result else None

        return await self._run(_get_author)

    async def _create_password_user(self, username: str, password_hash: str, metadata: Dict[str, Any]):
        """Internal method to create a user with password hash."""
        from chainlit.user import PersistedUser
        created_at = datetime.utcnow()

        def _create():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO users (username, password_hash, metadata, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        username,
                        password_hash,
                        self._serialize_metadata(metadata),
                        created_at,
                    ),
                )
                conn.commit()

        await self._run(_create)

        return PersistedUser(
            identifier=username,
            id=username,
            metadata=metadata,
            createdAt=created_at.isoformat(),
        )

    async def create_user(self, user: "cl.User"):
        from chainlit.user import PersistedUser
        created_at = datetime.utcnow()

        def _create_user():
            with self._connect() as conn:
                cursor = conn.cursor()
                # Use INSERT OR IGNORE to avoid overwriting existing password users
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO users (username, password_hash, metadata, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user.identifier,
                        "",  # password_hash not needed for OAuth users
                        self._serialize_metadata(user.metadata or {}),
                        created_at,
                    ),
                )
                conn.commit()

        await self._run(_create_user)

        return PersistedUser(
            identifier=user.identifier,
            id=user.identifier,
            metadata=user.metadata or {},
            createdAt=created_at.isoformat(),
        )

    async def get_user(self, identifier: str):
        def _get_user():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE username = ?", (identifier,))
                row = cursor.fetchone()
                if not row:
                    return None
                # Row structure: (username, password_hash, metadata, created_at)
                username = row[0]
                password_hash = row[1] or ""  # Column 1 is password_hash
                metadata_str = row[2] or "{}"
                created_at = row[3]

                if isinstance(created_at, datetime):
                    created_at_iso = created_at.isoformat()
                else:
                    created_at_iso = str(created_at) if created_at else None
                from chainlit.user import PersistedUser
                metadata = json.loads(metadata_str)
                # Store password_hash in metadata for internal use (from password_hash column!)
                metadata["_password_hash"] = password_hash
                return PersistedUser(
                    identifier=username,
                    id=username,
                    metadata=metadata,
                    createdAt=created_at_iso,
                )

        return await self._run(_get_user)

    async def _create_element_from_dict(self, element_dict: Dict[str, Any]):
        """Internal method for creating elements from dicts."""
        def _create():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO context_files (id, thread_id, step_id, name, path, type, mime_type, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        element_dict.get("id"),
                        element_dict.get("threadId"),
                        element_dict.get("stepId"),
                        element_dict.get("name"),
                        element_dict.get("path"),
                        element_dict.get("type"),
                        element_dict.get("mimeType"),
                        self._serialize_metadata(element_dict.get("metadata", {})),
                        datetime.utcnow(),
                    ),
                )
                conn.commit()

        await self._run(_create)

    async def create_element(self, element: "cl.Element"):
        def _create_element():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO context_files (id, thread_id, step_id, name, path, type, mime_type, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        element.id,
                        element.thread_id,
                        element.for_id,  # step_id
                        element.name,
                        element.path,
                        element.display or "inline",  # type
                        element.mime,
                        self._serialize_metadata({}),
                        datetime.utcnow(),
                    ),
                )
                conn.commit()

        await self._run(_create_element)

    async def get_element(self, thread_id: str, element_id: str):
        def _get_element():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM context_files WHERE id = ? AND thread_id = ?",
                    (element_id, thread_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                # Read the actual file content
                file_path = Path(row[4])  # path column
                content = None
                if file_path.exists():
                    try:
                        content = file_path.read_bytes()
                    except Exception as exc:
                        logger.warning("Failed to read file %s: %s", file_path, exc)

                return {
                    "id": row[0],
                    "threadId": row[1],
                    "forId": row[2],  # step_id
                    "name": row[3],
                    "path": row[4],
                    "type": row[5],
                    "mime": row[6],  # Use 'mime' not 'mimeType'
                    "metadata": json.loads(row[7] or "{}"),
                    "createdAt": row[8],
                    "content": content,  # Add actual file content
                }

        return await self._run(_get_element)

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None):
        def _delete_element():
            with self._connect() as conn:
                cursor = conn.cursor()
                if thread_id:
                    cursor.execute(
                        "DELETE FROM context_files WHERE id = ? AND thread_id = ?",
                        (element_id, thread_id),
                    )
                else:
                    cursor.execute("DELETE FROM context_files WHERE id = ?", (element_id,))
                conn.commit()

        await self._run(_delete_element)

    async def list_context_files(self, thread_id: str) -> List[Dict[str, Any]]:
        def _list_context_files():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM context_files WHERE thread_id = ? ORDER BY created_at",
                    (thread_id,),
                )
                rows = cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "threadId": row[1],
                        "stepId": row[2],
                        "name": row[3],
                        "path": row[4],
                        "type": row[5],
                        "mimeType": row[6],
                        "metadata": json.loads(row[7] or "{}"),
                        "createdAt": row[8],
                    }
                    for row in rows
                ]

        return await self._run(_list_context_files)

    async def upsert_feedback(self, feedback: "cl.types.Feedback") -> str:
        feedback_id = feedback.id or str(uuid.uuid4())

        def _upsert_feedback():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO feedback (id, thread_id, step_id, user_id, rating, comment, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feedback_id,
                        feedback.threadId,
                        feedback.forId,  # step_id
                        None,  # user_id - not provided in Feedback object
                        feedback.value,
                        feedback.comment,
                        datetime.utcnow(),
                        self._serialize_metadata({}),
                    ),
                )
                conn.commit()

        await self._run(_upsert_feedback)
        return feedback_id

    async def delete_feedback(self, feedback_id: str) -> bool:
        def _delete_feedback():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count > 0

        return await self._run(_delete_feedback)

    async def build_debug_url(self):
        return None

    async def close(self):
        return


class UserStore:
    def __init__(self, data_layer: "SQLiteDataLayer"):
        self.data_layer = data_layer
        self._bootstrapped = False
        self._lock = asyncio.Lock()

    async def ensure_bootstrap(self) -> None:
        if self._bootstrapped:
            return
        async with self._lock:
            if self._bootstrapped:
                return
            await self._create_seed_users()
            self._bootstrapped = True

    async def _create_seed_users(self) -> None:
        admin_username = os.getenv("CHAINLIT_ADMIN_USERNAME", "admin")
        admin_password = os.getenv("CHAINLIT_ADMIN_PASSWORD", "admin123")
        if admin_password == "admin123":
            logger.warning("Using default admin password; set CHAINLIT_ADMIN_PASSWORD for production use.")
        await self._ensure_user(admin_username, admin_password, roles=["admin"])

        env_users = os.getenv("CHAINLIT_USERS")
        if env_users:
            mapping = self._parse_user_mapping(env_users)
            for username, password in mapping.items():
                if username == admin_username:
                    continue
                await self._ensure_user(username, password, roles=["user"])

    def _parse_user_mapping(self, payload: str) -> Dict[str, str]:
        payload = payload.strip()
        if not payload:
            return {}
        try:
            if payload.startswith("{"):
                parsed = json.loads(payload)
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse CHAINLIT_USERS JSON: %s", exc)
        mapping: Dict[str, str] = {}
        for item in payload.split(","):
            if "=" not in item:
                continue
            username, password = item.split("=", 1)
            mapping[username.strip()] = password.strip()
        return mapping

    async def _ensure_user(self, username: str, password: str, roles: List[str]):
        existing = await self.data_layer.get_user(username)
        if existing:
            # If user exists but has no password hash, update it
            password_hash = existing.metadata.get("_password_hash", "")
            if not password_hash:
                logger.info("Updating password for existing user: %s", username)
                await self.data_layer._create_password_user(
                    username=username,
                    password_hash=hash_password(password),
                    metadata={"roles": roles, "email": username},
                )
            return
        await self.data_layer._create_password_user(
            username=username,
            password_hash=hash_password(password),
            metadata={"roles": roles, "email": username},
        )

    async def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        user = await self.data_layer.get_user(username)
        if not user:
            return None
        password_hash = user.metadata.get("_password_hash", "")
        if not verify_password(password, password_hash):
            return None
        # Remove internal password hash from metadata before returning
        clean_metadata = {k: v for k, v in user.metadata.items() if k != "_password_hash"}
        return {
            "username": username,
            "identifier": user.identifier,
            "id": user.id,
            "metadata": clean_metadata,
        }


class MCPToolClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional["httpx.AsyncClient"] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._client and not self._client.is_closed:
            return
        if httpx is None:
            raise RuntimeError("httpx is required for MCP integration. Add `httpx>=0.27.0` to requirements and install it.")
        async with self._lock:
            if self._client and not self._client.is_closed:
                return
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def list_tools(self) -> List[Dict[str, Any]]:
        try:
            await self.connect()
        except Exception as exc:  # pragma: no cover - network issues
            logger.warning("Could not connect to MCP server: %s", exc)
            return []
        assert self._client is not None
        try:
            response = await self._client.get("/tools")
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and "tools" in payload:
                tools = payload["tools"]
                if isinstance(tools, list):
                    return tools
        except Exception as exc:
            logger.warning("Failed to list MCP tools: %s", exc)
        return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        await self.connect()
        assert self._client is not None
        try:
            response = await self._client.post(
                f"/tools/{tool_name}",
                json={"arguments": arguments},
            )
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text
        except Exception as exc:
            logger.error("Tool %s invocation failed: %s", tool_name, exc)
            raise

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_data_layer_instance: Optional[SQLiteDataLayer] = None

# Ensure the Chainlit module exposes the decorator even if it was overridden earlier.
cl.data_layer = register_data_layer


@register_data_layer
def provide_data_layer() -> SQLiteDataLayer:
    """Register and reuse the custom SQLite data layer instance."""
    global _data_layer_instance
    if _data_layer_instance is None:
        _data_layer_instance = SQLiteDataLayer(DB_PATH)
    return _data_layer_instance


data_layer = provide_data_layer()
user_store = UserStore(data_layer)
ollama_client = AsyncClient(host=OLLAMA_HOST)


def get_session_state() -> ChatSessionState:
    state = cl.user_session.get("state")
    if isinstance(state, ChatSessionState):
        return state
    state = ChatSessionState()
    cl.user_session.set("state", state)
    return state


async def fetch_available_models() -> List[str]:
    """Fetch available models from Ollama server."""
    try:
        response = await ollama_client.list()
        # response.models is a list of Model objects, each with a 'model' attribute
        model_names = [model.model for model in response.models if hasattr(model, 'model')]
        if model_names:
            logger.info("Found %d models from Ollama: %s", len(model_names), ", ".join(model_names))
            return model_names
    except Exception as exc:
        logger.warning("Failed to fetch models from Ollama: %s", exc)
    # Fallback to env variable or default
    return MODEL_OPTIONS if MODEL_OPTIONS else [DEFAULT_MODEL]


async def generate_chat_name(user_message: str, assistant_response: str) -> str:
    """Generate a concise chat name based on the first exchange."""
    try:
        # Create a prompt to generate a short title
        prompt = f"""Based on this conversation, generate a very short title (3-6 words max) that captures the main topic.

User: {user_message[:200]}
Assistant: {assistant_response[:200]}

Generate only the title, nothing else. No quotes, no punctuation at the end."""

        response = await ollama_client.generate(
            model=DEFAULT_MODEL,
            prompt=prompt,
            options={"temperature": 0.3},
        )

        title = response.get("response", "").strip()
        # Clean up the title
        title = title.strip('"\'.,!?;:')
        # Limit length
        if len(title) > 50:
            title = title[:47] + "..."

        if title:
            logger.info("Generated chat name: %s", title)
            return title
    except Exception as exc:
        logger.warning("Failed to generate chat name: %s", exc)

    # Fallback: use first few words of user message
    words = user_message.split()[:5]
    fallback = " ".join(words)
    if len(fallback) > 40:
        fallback = fallback[:37] + "..."
    return fallback or "New Chat"


def trim_history(state: ChatSessionState) -> None:
    if len(state.messages) <= HISTORY_MESSAGE_LIMIT:
        return
    excess = len(state.messages) - HISTORY_MESSAGE_LIMIT
    del state.messages[0:excess]


async def ensure_thread(user: Optional[cl.User]) -> str:
    # Check if Chainlit already has a thread_id
    thread_id = getattr(cl.context.session, "thread_id", None)
    if not thread_id:
        thread_id = cl.user_session.get("thread_id")

    # If we have a thread_id, check if it exists in the database
    if thread_id:
        existing_thread = await data_layer.get_thread(thread_id)
        if existing_thread:
            cl.user_session.set("thread_id", thread_id)
            return thread_id

    # Create a new thread if we don't have one or it doesn't exist in DB
    if not thread_id:
        thread_id = str(uuid.uuid4())

    await data_layer.create_thread(
        {
            "id": thread_id,
            "userId": getattr(user, "identifier", "anonymous"),
            "name": f"Conversation {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            "metadata": {"created_from": "app.py"},
        }
    )
    cl.user_session.set("thread_id", thread_id)
    return thread_id


async def persist_element(element: Any, thread_id: str, step_id: str) -> Optional[Dict[str, Any]]:
    name = getattr(element, "name", None) or f"attachment-{uuid.uuid4().hex}"
    raw_content = getattr(element, "content", None)
    if isinstance(raw_content, str):
        data = raw_content.encode("utf-8")
    elif isinstance(raw_content, bytes):
        data = raw_content
    else:
        path_attr = getattr(element, "path", None)
        data = None
        if path_attr:
            src_path = Path(path_attr)
            if src_path.exists():
                data = src_path.read_bytes()
    if data is None:
        logger.warning("Ignoring attachment %s; unable to access bytes.", name)
        return None

    dest_dir = UPLOADS_DIR / thread_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / name
    dest_path.write_bytes(data)

    mime_type, _ = mimetypes.guess_type(dest_path.name)
    kind = "image" if mime_type and mime_type.startswith("image/") else "document"
    entry = {
        "id": getattr(element, "id", uuid.uuid4().hex),
        "name": name,
        "path": str(dest_path),
        "type": kind,
        "mime_type": mime_type or "application/octet-stream",
        "created_at": current_timestamp(),
        "preview": None,
        "base64": None,
    }

    if kind == "image":
        entry["base64"] = base64.b64encode(data).decode("utf-8")
    else:
        entry["preview"] = build_document_preview(dest_path)

    await data_layer._create_element_from_dict(
        {
            "id": entry["id"],
            "threadId": thread_id,
            "stepId": step_id,
            "name": entry["name"],
            "type": entry["type"],
            "path": entry["path"],
            "mimeType": entry["mime_type"],
            "metadata": {"preview": entry["preview"]},
        }
    )

    return entry


def build_document_preview(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        # For PDFs, return a placeholder that will be processed async
        return f"[PDF Document: {path.name} - Processing with OCR...]"
    elif path.suffix.lower() in TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return text[:MAX_DOC_PREVIEW_CHARS]
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
    return f"Stored file at {path.name}. Provide instructions if you need it summarized."


async def handle_uploaded_elements(message: cl.Message, state: ChatSessionState, thread_id: str, step_id: str) -> List[Dict[str, Any]]:
    elements = getattr(message, "elements", None) or []
    if not elements:
        return []
    new_entries: List[Dict[str, Any]] = []
    for element in elements:
        saved = await persist_element(element, thread_id, step_id)
        if not saved:
            continue

        # If it's a PDF, extract text
        if saved.get("mime_type") == "application/pdf":
            pdf_path = Path(saved["path"])
            extracted_text = extract_pdf_text_safe(pdf_path, max_pages=35)
            saved["preview"] = extracted_text
            logger.info("Updated PDF preview for %s with %d chars", saved["name"], len(extracted_text))

        state.context_files = [item for item in state.context_files if item.get("id") != saved["id"]]
        state.context_files.append(saved)
        new_entries.append(saved)
    return new_entries






@cl.on_mcp_connect
async def on_mcp_connect(connection, session):
    """Called when an MCP connection is established."""
    from mcp import ClientSession

    logger.info("MCP connect handler called for connection: %s (type: %s)", connection.name, type(session))

    if not isinstance(session, ClientSession):
        logger.warning("Invalid MCP session type: %s", type(session))
        return

    try:
        # List available tools
        result = await session.list_tools()
        logger.info("MCP session.list_tools() returned: %s", result)

        # Process tool metadata
        tools = [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.inputSchema,
        } for t in result.tools]

        # Store tools for later use
        mcp_tools = cl.user_session.get("mcp_tools", {})
        mcp_tools[connection.name] = tools
        cl.user_session.set("mcp_tools", mcp_tools)

        logger.info("MCP connection '%s' established with %d tools: %s",
                   connection.name, len(tools), [t["name"] for t in tools])
    except Exception as exc:
        logger.error("Failed to initialize MCP connection '%s': %s", connection.name, exc, exc_info=True)


@cl.on_mcp_disconnect
async def on_mcp_disconnect(name: str, session):
    """Called when an MCP connection is terminated."""
    mcp_tools = cl.user_session.get("mcp_tools", {})
    if name in mcp_tools:
        del mcp_tools[name]
        cl.user_session.set("mcp_tools", mcp_tools)
    logger.info("MCP connection '%s' disconnected", name)


@cl.password_auth_callback
async def password_auth(username: str, password: str):
    await user_store.ensure_bootstrap()
    authenticated = await user_store.authenticate(username, password)
    if not authenticated:
        return None
    return cl.User(
        identifier=authenticated["identifier"],
        id=authenticated.get("id", authenticated["identifier"]),
        metadata=authenticated.get("metadata"),
    )


@cl.on_chat_start
async def on_chat_start():
    user: Optional[cl.User] = cl.user_session.get("user")
    await user_store.ensure_bootstrap()
    state = get_session_state()

    # Fetch available models from Ollama
    available_models = await fetch_available_models()

    model = state.settings.get("model") or DEFAULT_MODEL
    if model not in available_models:
        available_models.append(model)
    state.settings["model"] = model
    model_index = available_models.index(model)

    await cl.ChatSettings(
        [
            input_widget.Select(
                id="model",
                label="Model",
                values=available_models,
                initial_index=model_index,
            ),
            input_widget.Slider(
                id="temperature",
                label="Temperature",
                min=0.0,
                max=1.0,
                step=0.05,
                initial=state.settings.get("temperature", 0.2),
            ),
            input_widget.Switch(
                id="use_tools",
                label="Allow tool use",
                initial=state.settings.get("use_tools", True),
            ),
            input_widget.TextInput(
                id="system_prompt",
                label="System prompt",
                initial=state.settings.get("system_prompt", DEFAULT_SYSTEM_PROMPT.strip()),
                multiline=True,
            ),
        ],
        settings=state.settings,
    ).send()

    # Initialize message history
    cl.user_session.set("message_history", [])

    # Wait a moment for MCP connections to establish
    await cl.sleep(0.5)

    name = getattr(user, "identifier", "Guest")
    logger.info("Started chat session for user %s", name)


@cl.on_chat_resume
async def on_chat_resume(thread: Dict[str, Any]):
    user: Optional[cl.User] = cl.user_session.get("user")
    thread_id = thread.get("id")

    # Check if thread exists in database
    existing_thread = await data_layer.get_thread(thread_id)

    # Only create thread if it has steps (actual conversation)
    if not existing_thread:
        steps = thread.get("steps", [])
        if steps:
            logger.info("Thread %s not found in database but has steps, creating it", thread_id)
            await data_layer.create_thread({
                "id": thread_id,
                "userId": getattr(user, "identifier", "anonymous"),
                "name": thread.get("name", f"Conversation {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"),
                "metadata": {},
            })
        else:
            # Empty thread, don't persist it
            logger.debug("Thread %s is empty, not persisting to database", thread_id)

    cl.user_session.set("thread_id", thread_id)
    state = get_session_state()
    state.messages = []

    # Load steps from the thread dict or database
    steps = thread.get("steps", [])
    if not steps and existing_thread:
        steps = existing_thread.get("steps", [])

    for step in steps:
        role = "assistant" if step.get("type") in {"assistant_message", "assistant"} else "user"
        content = step.get("output", "")
        if content:  # Only add non-empty messages
            state.messages.append({"role": role, "content": content})

    context_records = await data_layer.list_context_files(thread_id)
    state.context_files = []
    for record in context_records:
        path = Path(record.get("path", ""))
        entry = {
            "id": record.get("id"),
            "name": record.get("name"),
            "path": record.get("path"),
            "type": record.get("type"),
            "mime_type": record.get("mimeType") or record.get("mime_type"),
            "preview": (record.get("metadata") or {}).get("preview"),
            "base64": None,
        }
        if entry["type"] == "image" and path.exists():
            try:
                entry["base64"] = base64.b64encode(path.read_bytes()).decode("utf-8")
            except Exception as exc:
                logger.warning("Failed to reload image %s: %s", path, exc)
        state.context_files.append(entry)

    # Fetch available models and send chat settings
    available_models = await fetch_available_models()
    model = state.settings.get("model") or DEFAULT_MODEL
    if model not in available_models:
        available_models.append(model)
    state.settings["model"] = model
    model_index = available_models.index(model)

    await cl.ChatSettings(
        [
            input_widget.Select(
                id="model",
                label="Model",
                values=available_models,
                initial_index=model_index,
            ),
            input_widget.Slider(
                id="temperature",
                label="Temperature",
                min=0.0,
                max=1.0,
                step=0.05,
                initial=state.settings.get("temperature", 0.2),
            ),
            input_widget.Switch(
                id="use_tools",
                label="Allow tool use",
                initial=state.settings.get("use_tools", True),
            ),
            input_widget.TextInput(
                id="system_prompt",
                label="System prompt",
                initial=state.settings.get("system_prompt", DEFAULT_SYSTEM_PROMPT.strip()),
                multiline=True,
            ),
        ],
        settings=state.settings,
    ).send()

    name = getattr(user, "identifier", "Guest")
    message_count = len([m for m in state.messages if m.get("content")])
    logger.info("Resumed chat for %s with %d messages and %d attachments", name, message_count, len(state.context_files))


@cl.on_settings_update
async def on_settings_update(settings: Dict[str, Any]):
    state = get_session_state()
    state.settings.update(settings)
    model = settings.get("model")
    if model and model not in MODEL_OPTIONS:
        MODEL_OPTIONS.append(model)

    await cl.Message(author="Assistant", content="Updated chat settings.").send()


@cl.on_message
async def on_message(message: cl.Message):
    state = get_session_state()
    user: Optional[cl.User] = cl.user_session.get("user")
    thread_id = await ensure_thread(user)

    user_step_id = getattr(message, "id", None) or str(uuid.uuid4())
    new_context = await handle_uploaded_elements(message, state, thread_id, user_step_id)

    user_text = message.content or ""
    if not user_text:
        return

    # Get and update message history
    message_history = cl.user_session.get("message_history", [])
    message_history.append({"role": "user", "content": user_text})

    # Get MCP tools
    mcp_tools = cl.user_session.get("mcp_tools", {})

    # Build available_tools dict
    available_tools = {}
    for mcp_name, tools in mcp_tools.items():
        for tool in tools:
            available_tools[tool["name"]] = {
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema", {})
            }

    # Get MCP sessions
    mcp_sessions = {}
    if hasattr(cl.context.session, "mcp_sessions"):
        mcp_sessions = cl.context.session.mcp_sessions

    if not available_tools or not mcp_sessions:
        await cl.Message(
            content="⚠️ MCP tools not available yet. Please wait a moment and try again."
        ).send()
        return

    logger.info(f"Processing query with {len(available_tools)} tools available")

    try:
        # Use LangGraph agent to process the query
        # The agent will stream the final answer
        answer = await langgraph_process_query(
            query=user_text,
            available_tools=available_tools,
            mcp_sessions=mcp_sessions,
            max_iterations=3,
            message_history=message_history,
            context_files=state.context_files  # Pass uploaded files to agent
        )

        # Store assistant response in history
        if answer and answer != "No answer generated":
            message_history.append({"role": "assistant", "content": answer})
            cl.user_session.set("message_history", message_history)

            # Also update state.messages for compatibility
            state.messages.append({"role": "user", "content": user_text})
            state.messages.append({"role": "assistant", "content": answer})
            trim_history(state)

            # Persist assistant response as a step
            await data_layer.create_step({
                "id": str(uuid.uuid4()),
                "threadId": thread_id,
                "type": "assistant_message",
                "name": "Assistant",
                "output": answer,
                "metadata": {"langgraph": True},
            })

            # Generate chat name after first exchange
            if len(state.messages) == 2:
                chat_name = await generate_chat_name(user_text, answer)
                await data_layer.update_thread(thread_id, name=chat_name)
                logger.info("Updated thread %s name to: %s", thread_id, chat_name)

        # Streaming is handled inside langgraph_agent.py
        # Just check if an answer was generated
        if not answer or answer == "No answer generated":
            await cl.Message(
                content="⚠️ No answer was generated. Check the steps above for details.",
                author="System"
            ).send()

    except Exception as e:
        logger.exception(f"Error processing query: {e}")

        error_msg = f"""❌ **Error**

{str(e)}

Check terminal logs for details."""
        await cl.Message(content=error_msg).send()


@cl.on_stop
async def on_stop():
    pass


@cl.on_chat_end
async def on_chat_end():
    pass


@cl.on_logout
async def on_logout(user: Optional[cl.User]):
    """Reset user session state on logout so the UI can start fresh."""
    # Session is automatically cleared by Chainlit on logout
    # Attempting to access cl.user_session here will raise ChainlitContextException
    logger.info("User %s logged out", user.identifier if user else "unknown")
