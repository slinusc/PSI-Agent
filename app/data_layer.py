"""
SQLite Data Layer for Chainlit

Handles all database operations for threads, steps, users, context files, and feedback.
"""

import asyncio
import base64
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chainlit as cl
from chainlit.data import BaseDataLayer

logger = logging.getLogger("psi.chainlit.data_layer")


class SQLiteDataLayer(BaseDataLayer):
    """Custom SQLite-based data persistence layer for Chainlit."""

    def __init__(self, db_path: Path, uploads_dir: Path):
        self.db_path = Path(db_path)
        self.uploads_dir = Path(uploads_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
        """Add a column to a table if it doesn't exist."""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        """Initialize database schema."""
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
        """Run a synchronous function in a thread pool."""
        return await asyncio.to_thread(func, *args)

    def _serialize_metadata(self, payload: Optional[Dict[str, Any]]) -> str:
        """Serialize metadata dict to JSON string."""
        return json.dumps(payload or {}, ensure_ascii=False)

    # =========================================================================
    # STEPS
    # =========================================================================

    async def create_step(self, step_dict: Dict[str, Any]):
        """Create a step, filtering out intermediate agentic steps."""
        # Filter out intermediate agentic steps - only persist actual messages
        step_name = step_dict.get("name", "")
        step_type = step_dict.get("type", "")
        step_output = step_dict.get("output", "")

        # Skip intermediate steps like "Decision: Tools Needed?", "Selected X Tool(s)", etc.
        # Also skip "thinking..." as it's confusing in history view
        intermediate_step_names = [
            "Decision: Tools Needed?",
            "Tool(s)",  # Matches "Selected 1 Tool(s)", etc.
            "Executing:",
            "Evaluation",
            "Analyzing",  # Image analysis steps
            "thinking...",  # Skip "Used thinking..." steps in history
        ]

        # Don't persist if it's an intermediate step
        if any(name in step_name for name in intermediate_step_names):
            logger.debug("Skipping intermediate step: %s", step_name)
            return

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

    async def update_step(self, step_dict: Dict[str, Any]):
        """Update an existing step."""
        await self.create_step(step_dict)

    async def delete_step(self, step_id: str):
        """Delete a step."""

        def _delete_step():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM steps WHERE id = ?", (step_id,))
                conn.commit()

        await self._run(_delete_step)

    # =========================================================================
    # THREADS
    # =========================================================================

    async def get_thread(self, thread_id: str):
        """Retrieve a thread with all its steps and elements."""

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
                                b64 = base64.b64encode(content).decode("utf-8")
                                url = f"data:{e[6]};base64,{b64}"
                            except Exception as ex:
                                logger.warning("Failed to read image %s: %s", file_path, ex)

                    elements.append(
                        {
                            "id": e[0],
                            "threadId": e[1],
                            "forId": e[2],
                            "name": e[3],
                            "url": url,  # Use data URL for images
                            "display": "inline",
                            "type": element_type,
                            "mime": e[6],
                            "objectKey": e[4],
                        }
                    )

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
        """List threads with pagination and filtering."""
        from chainlit.types import PageInfo, PaginatedResponse

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
        """Create a new thread."""

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

    async def update_thread(
        self,
        thread_id: str,
        name: str = None,
        user_id: str = None,
        metadata: dict = None,
        tags: list = None,
    ):
        """Update thread metadata."""

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

    async def delete_thread(self, thread_id: str):
        """Delete a thread and all associated data."""

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
                thread_dir = self.uploads_dir / thread_id
                if thread_dir.exists():
                    try:
                        thread_dir.rmdir()  # Only works if directory is empty
                        logger.info("Deleted empty directory: %s", thread_dir)
                    except OSError:
                        pass  # Directory not empty or other error, ignore

        await self._run(_delete_thread)

    async def get_thread_author(self, thread_id: str):
        """Get the author (user_id) of a thread."""

        def _get_author():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM threads WHERE id = ?", (thread_id,))
                result = cursor.fetchone()
                return result[0] if result else None

        return await self._run(_get_author)

    # =========================================================================
    # USERS
    # =========================================================================

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
        """Create a new user."""
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
        """Retrieve a user by identifier."""

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

    # =========================================================================
    # ELEMENTS (Context Files)
    # =========================================================================

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
        """Create a context file element."""

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
        """Retrieve an element with its file content."""

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
        """Delete an element."""

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
        """List all context files for a thread."""

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

    # =========================================================================
    # FEEDBACK
    # =========================================================================

    async def upsert_feedback(self, feedback: "cl.types.Feedback") -> str:
        """Create or update feedback."""
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
        """Delete feedback."""

        def _delete_feedback():
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count > 0

        return await self._run(_delete_feedback)

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def build_debug_url(self):
        """Build debug URL (not implemented)."""
        return None

    async def close(self):
        """Close the data layer (SQLite doesn't require explicit close)."""
        return
