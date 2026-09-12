from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import asyncpg


class PersistenceError(RuntimeError):
    pass


_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise PersistenceError("DATABASE_URL is not configured.")
        try:
            _pool = await asyncpg.create_pool(
                dsn=database_url,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
        except Exception as error:
            raise PersistenceError("PostgreSQL is unavailable.") from error
    return _pool


async def ensure_session(session_id: str, *, scope: str = "chat") -> None:
    pool = await _get_pool()
    try:
        await pool.execute(
            """
            INSERT INTO agent_sessions (session_id, scope, status)
            VALUES ($1::uuid, $2, 'active')
            ON CONFLICT (session_id) DO UPDATE
            SET status = 'active', updated_at = NOW()
            """,
            session_id,
            scope,
        )
    except Exception as error:
        raise PersistenceError("Could not create or update the agent session.") from error


async def load_message_history(
    session_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT message_json
            FROM (
                SELECT sequence_number, message_json
                FROM agent_messages
                WHERE session_id = $1::uuid
                ORDER BY sequence_number DESC
                LIMIT $2
            ) recent
            ORDER BY sequence_number ASC
            """,
            session_id,
            limit,
        )
    except Exception as error:
        raise PersistenceError("Could not load the agent session history.") from error
    history: list[dict[str, Any]] = []
    for row in rows:
        message_json = row["message_json"]
        if isinstance(message_json, str):
            message_json = json.loads(message_json)
        if not isinstance(message_json, dict):
            raise PersistenceError("Stored agent history has an invalid message.")
        history.append(message_json)
    return history


async def create_run(
    *,
    run_id: str,
    session_id: str,
    user_prompt: str,
    provider_name: str,
    model_name: str,
) -> None:
    pool = await _get_pool()
    try:
        await pool.execute(
            """
            INSERT INTO agent_runs (
                run_id,
                session_id,
                status,
                user_prompt,
                provider_name,
                model_name
            )
            VALUES ($1::uuid, $2::uuid, 'running', $3, $4, $5)
            """,
            run_id,
            session_id,
            user_prompt,
            provider_name,
            model_name,
        )
    except Exception as error:
        raise PersistenceError("Could not create the agent run.") from error


async def finish_run(
    *,
    run_id: str,
    status: str,
    error_code: str | None = None,
) -> None:
    if status not in {"succeeded", "failed"}:
        raise ValueError("invalid run status")
    pool = await _get_pool()
    try:
        await pool.execute(
            """
            UPDATE agent_runs
            SET status = $2, error_code = $3, finished_at = NOW()
            WHERE run_id = $1::uuid
            """,
            run_id,
            status,
            error_code,
        )
    except Exception as error:
        raise PersistenceError("Could not finish the agent run.") from error


async def append_new_messages(
    *,
    session_id: str,
    run_id: str,
    new_messages_json: bytes | str,
) -> int:
    try:
        raw_messages = json.loads(
            new_messages_json.decode("utf-8")
            if isinstance(new_messages_json, bytes)
            else new_messages_json
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PersistenceError("The agent returned invalid message history.") from error

    if not isinstance(raw_messages, list) or not all(
        isinstance(message, dict) for message in raw_messages
    ):
        raise PersistenceError("The agent returned invalid message history.")

    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                next_sequence = await connection.fetchval(
                    """
                    SELECT COALESCE(MAX(sequence_number), 0) + 1
                    FROM agent_messages
                    WHERE session_id = $1::uuid
                    """,
                    session_id,
                )
                for offset, message in enumerate(raw_messages):
                    await connection.execute(
                        """
                        INSERT INTO agent_messages (
                            session_id,
                            run_id,
                            sequence_number,
                            message_json
                        )
                        VALUES ($1::uuid, $2::uuid, $3, $4::jsonb)
                        """,
                        session_id,
                        run_id,
                        next_sequence + offset,
                        json.dumps(message, separators=(",", ":")),
                    )
                await connection.execute(
                    """
                    UPDATE agent_sessions
                    SET updated_at = NOW()
                    WHERE session_id = $1::uuid
                    """,
                    session_id,
                )
    except PersistenceError:
        raise
    except Exception as error:
        raise PersistenceError("Could not persist the agent messages.") from error
    return len(raw_messages)


async def record_tool_event(
    *,
    run_id: str,
    tool_name: str,
    status: str,
    duration_ms: int | None,
    safe_metadata: dict[str, Any] | None,
) -> None:
    if status not in {"success", "failed"}:
        raise ValueError("invalid tool event status")
    pool = await _get_pool()
    try:
        await pool.execute(
            """
            INSERT INTO tool_events (
                run_id,
                tool_name,
                status,
                duration_ms,
                safe_metadata
            )
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
            """,
            run_id,
            tool_name,
            status,
            duration_ms,
            json.dumps(safe_metadata or {}, separators=(",", ":")),
        )
    except Exception as error:
        raise PersistenceError("Could not persist the tool event.") from error


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None