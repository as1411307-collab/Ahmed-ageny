from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from collections.abc import Sequence
from typing import Any

import asyncpg


class PersistenceError(RuntimeError):
    pass


_pool: asyncpg.Pool | None = None
_schema_ready = False
_schema_lock = asyncio.Lock()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def _ensure_policy_schema(pool: asyncpg.Pool) -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        try:
            await pool.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    action_id UUID PRIMARY KEY,
                    session_id UUID NOT NULL,
                    run_id UUID NOT NULL,
                    user_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    arguments_json JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes'),
                    approved_at TIMESTAMPTZ,
                    rejected_at TIMESTAMPTZ,
                    executed_at TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS pending_actions_user_status_idx
                    ON pending_actions (user_id, status, created_at DESC);

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id BIGSERIAL PRIMARY KEY,
                    session_id UUID,
                    run_id UUID,
                    action_id UUID,
                    event_type TEXT NOT NULL,
                    tool_name TEXT,
                    status TEXT NOT NULL,
                    safe_metadata JSONB,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS audit_events_created_idx
                    ON audit_events (created_at, event_id);

                CREATE TABLE IF NOT EXISTS agent_run_checkpoints (
                    checkpoint_id BIGSERIAL PRIMARY KEY,
                    session_id UUID NOT NULL,
                    run_id UUID NOT NULL,
                    stage TEXT NOT NULL,
                    state_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS agent_run_checkpoints_run_idx
                    ON agent_run_checkpoints (run_id, checkpoint_id);

                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'created';
                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS worker_id TEXT;
                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS lease_version BIGINT NOT NULL DEFAULT 0;
                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE agent_runs
                    ADD COLUMN IF NOT EXISTS last_checkpoint_at TIMESTAMPTZ;

                ALTER TABLE pending_actions
                    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
                CREATE UNIQUE INDEX IF NOT EXISTS pending_actions_run_idempotency_idx
                    ON pending_actions (run_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                """
            )
            _schema_ready = True
        except Exception as error:
            raise PersistenceError("Could not initialize policy persistence.") from error


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
    await _ensure_policy_schema(_pool)
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
    worker_id: str | None = None,
    lease_seconds: int = 120,
) -> None:
    if lease_seconds < 30 or lease_seconds > 900:
        raise ValueError("invalid run lease")
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
                model_name,
                stage,
                worker_id,
                lease_expires_at,
                lease_version,
                attempt_count
            )
            VALUES (
                $1::uuid,
                $2::uuid,
                'running',
                $3,
                $4,
                $5,
                'created',
                $6,
                NOW() + ($7::integer * INTERVAL '1 second'),
                1,
                1
            )
            """,
            run_id,
            session_id,
            user_prompt,
            provider_name,
            model_name,
            worker_id,
            lease_seconds,
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
            SET status = $2,
                error_code = $3,
                finished_at = NOW(),
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE run_id = $1::uuid
            """,
            run_id,
            status,
            error_code,
        )
    except Exception as error:
        raise PersistenceError("Could not finish the agent run.") from error


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def renew_run_lease(
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int = 120,
) -> bool:
    if not worker_id or lease_seconds < 30 or lease_seconds > 900:
        raise ValueError("invalid run lease")
    pool = await _get_pool()
    try:
        updated = await pool.execute(
            """
            UPDATE agent_runs
            SET lease_expires_at = NOW() + ($3::integer * INTERVAL '1 second'),
                lease_version = lease_version + 1
            WHERE run_id = $1::uuid
              AND status = 'running'
              AND worker_id = $2
              AND lease_expires_at > NOW()
            """,
            run_id,
            worker_id,
            lease_seconds,
        )
    except Exception as error:
        raise PersistenceError("Could not renew the agent run lease.") from error
    return updated.endswith("1")


async def mark_orphaned_runs() -> list[str]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            UPDATE agent_runs
            SET status = 'orphaned',
                error_code = 'WORKER_LOST',
                worker_id = NULL,
                lease_expires_at = NULL,
                finished_at = NULL
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= NOW()
            RETURNING run_id
            """
        )
    except Exception as error:
        raise PersistenceError("Could not mark orphaned agent runs.") from error
    return [str(row["run_id"]) for row in rows]


async def load_run_recovery(run_id: str) -> dict[str, Any] | None:
    pool = await _get_pool()
    try:
        row = await pool.fetchrow(
            """
            SELECT run_id, session_id, status, stage, provider_name, model_name,
                   error_code, worker_id, lease_expires_at, attempt_count,
                   created_at, finished_at
            FROM agent_runs
            WHERE run_id = $1::uuid
            """,
            run_id,
        )
    except Exception as error:
        raise PersistenceError("Could not load run recovery state.") from error
    if row is None:
        return None
    return {
        "run_id": str(row["run_id"]),
        "session_id": str(row["session_id"]),
        "status": row["status"],
        "stage": row["stage"],
        "provider": row["provider_name"],
        "model": row["model_name"],
        "error_code": row["error_code"],
        "worker_id": row["worker_id"],
        "lease_expires_at": (
            row["lease_expires_at"].isoformat() if row["lease_expires_at"] else None
        ),
        "attempt_count": row["attempt_count"],
        "created_at": row["created_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


async def claim_orphaned_run(
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int = 120,
) -> dict[str, Any] | None:
    if not worker_id or lease_seconds < 30 or lease_seconds > 900:
        raise ValueError("invalid run lease")
    pool = await _get_pool()
    try:
        row = await pool.fetchrow(
            """
            UPDATE agent_runs
            SET status = 'running',
                worker_id = $2,
                lease_expires_at = NOW() + ($3::integer * INTERVAL '1 second'),
                lease_version = lease_version + 1,
                attempt_count = attempt_count + 1
            WHERE run_id = $1::uuid
              AND (
                  status = 'orphaned'
                  OR (status = 'running' AND lease_expires_at <= NOW())
              )
              AND (lease_expires_at IS NULL OR lease_expires_at <= NOW())
            RETURNING run_id, session_id, status, stage, provider_name, model_name,
                      error_code, attempt_count
            """,
            run_id,
            worker_id,
            lease_seconds,
        )
    except Exception as error:
        raise PersistenceError("Could not claim the orphaned run.") from error
    return dict(row) if row else None


async def release_orphaned_run(*, run_id: str, worker_id: str) -> bool:
    pool = await _get_pool()
    try:
        updated = await pool.execute(
            """
            UPDATE agent_runs
            SET status = 'orphaned',
                error_code = 'RECOVERY_REQUIRES_NEW_RUN',
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE run_id = $1::uuid
              AND status = 'running'
              AND worker_id = $2
            """,
            run_id,
            worker_id,
        )
    except Exception as error:
        raise PersistenceError("Could not release the recovered agent run.") from error
    return updated.endswith("1")


async def run_message_count(run_id: str) -> int:
    pool = await _get_pool()
    try:
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM agent_messages WHERE run_id = $1::uuid",
            run_id,
        )
    except Exception as error:
        raise PersistenceError("Could not inspect persisted run messages.") from error
    return int(count or 0)


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


async def record_run_checkpoint(
    *,
    session_id: str,
    run_id: str,
    stage: str,
    state: dict[str, Any],
) -> None:
    if not stage or len(stage) > 64:
        raise ValueError("invalid checkpoint stage")
    try:
        state_json = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("checkpoint state must be JSON serializable") from error

    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO agent_run_checkpoints (
                        session_id,
                        run_id,
                        stage,
                        state_json
                    )
                    VALUES ($1::uuid, $2::uuid, $3, $4::jsonb)
                    """,
                    session_id,
                    run_id,
                    stage,
                    state_json,
                )
                await connection.execute(
                    """
                    UPDATE agent_runs
                    SET stage = $2,
                        last_checkpoint_at = NOW()
                    WHERE run_id = $1::uuid
                    """,
                    run_id,
                    stage,
                )
                await _append_audit_event(
                    connection,
                    session_id=session_id,
                    run_id=run_id,
                    action_id=None,
                    event_type="run.checkpoint",
                    tool_name=None,
                    status=stage,
                    safe_metadata={"stage": stage},
                )
    except PersistenceError:
        raise
    except Exception as error:
        raise PersistenceError("Could not persist the run checkpoint.") from error


async def load_run_checkpoints(
    *,
    run_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise ValueError("invalid checkpoint limit")
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT checkpoint_id, session_id, run_id, stage, state_json, created_at
            FROM agent_run_checkpoints
            WHERE run_id = $1::uuid
            ORDER BY checkpoint_id ASC
            LIMIT $2
            """,
            run_id,
            limit,
        )
    except Exception as error:
        raise PersistenceError("Could not load run checkpoints.") from error
    checkpoints: list[dict[str, Any]] = []
    for row in rows:
        state = row["state_json"]
        if isinstance(state, str):
            state = json.loads(state)
        checkpoints.append(
            {
                "checkpoint_id": row["checkpoint_id"],
                "session_id": str(row["session_id"]),
                "run_id": str(row["run_id"]),
                "stage": row["stage"],
                "state": state,
                "created_at": row["created_at"].isoformat(),
            }
        )
    return checkpoints


async def record_auth_event(
    *,
    principal: str,
    authenticated: bool,
    endpoint: str,
    action_id: str | None,
    result: str,
) -> None:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await _append_audit_event(
                    connection,
                    session_id=None,
                    run_id=None,
                    action_id=action_id,
                    event_type="auth.authorization",
                    tool_name=None,
                    status=result,
                    safe_metadata={
                        "principal": principal,
                        "authenticated": authenticated,
                        "endpoint": endpoint,
                        "action_id": action_id,
                        "result": result,
                    },
                )
    except Exception as error:
        raise PersistenceError("Could not persist the authorization event.") from error


async def _append_audit_event(
    connection: asyncpg.Connection,
    *,
    session_id: str | None,
    run_id: str | None,
    action_id: str | None,
    event_type: str,
    tool_name: str | None,
    status: str,
    safe_metadata: dict[str, Any] | None,
) -> int:
    previous_hash = await connection.fetchval(
        """
        SELECT event_hash
        FROM audit_events
        ORDER BY event_id DESC
        LIMIT 1
        FOR UPDATE
        """
    )
    payload = {
        "session_id": session_id,
        "run_id": run_id,
        "action_id": action_id,
        "event_type": event_type,
        "tool_name": tool_name,
        "status": status,
        "safe_metadata": safe_metadata or {},
        "previous_hash": previous_hash,
    }
    event_hash = hashlib.sha256(
        ((previous_hash or "") + _canonical_json(payload)).encode("utf-8")
    ).hexdigest()
    return await connection.fetchval(
        """
        INSERT INTO audit_events (
            session_id,
            run_id,
            action_id,
            event_type,
            tool_name,
            status,
            safe_metadata,
            previous_hash,
            event_hash
        )
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7::jsonb, $8, $9)
        RETURNING event_id
        """,
        session_id,
        run_id,
        action_id,
        event_type,
        tool_name,
        status,
        json.dumps(safe_metadata or {}, separators=(",", ":")),
        previous_hash,
        event_hash,
    )


async def create_pending_action(
    *,
    action_id: str,
    session_id: str,
    run_id: str,
    user_id: str,
    tool_name: str,
    risk_level: str,
    arguments: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO pending_actions (
                        action_id,
                        session_id,
                        run_id,
                        user_id,
                        tool_name,
                        risk_level,
                        arguments_json,
                        idempotency_key
                    )
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7::jsonb, $8)
                    ON CONFLICT (run_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL
                    DO NOTHING
                    """,
                    action_id,
                    session_id,
                    run_id,
                    user_id,
                    tool_name,
                    risk_level,
                    json.dumps(arguments, separators=(",", ":")),
                    idempotency_key,
                )
                existing = await connection.fetchrow(
                    """
                    SELECT action_id, session_id, run_id, user_id, tool_name,
                           risk_level, status, created_at, expires_at
                    FROM pending_actions
                    WHERE run_id = $1::uuid
                      AND idempotency_key = $2
                    """,
                    run_id,
                    idempotency_key,
                ) if idempotency_key else None
                if existing is not None:
                    return dict(existing)
                await _append_audit_event(
                    connection,
                    session_id=session_id,
                    run_id=run_id,
                    action_id=action_id,
                    event_type="pending_action.created",
                    tool_name=tool_name,
                    status="pending",
                    safe_metadata={"risk_level": risk_level},
                )
                row = await connection.fetchrow(
                    """
                    SELECT action_id, session_id, run_id, user_id, tool_name,
                           risk_level, status, created_at, expires_at
                    FROM pending_actions
                    WHERE action_id = $1::uuid
                    """,
                    action_id,
                )
    except Exception as error:
        raise PersistenceError("Could not create the pending action.") from error
    return dict(row)


async def approve_pending_action(
    *,
    action_id: str,
    user_id: str,
) -> dict[str, Any]:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT action_id, session_id, run_id, user_id, tool_name,
                           risk_level, status, expires_at
                    FROM pending_actions
                    WHERE action_id = $1::uuid
                    FOR UPDATE
                    """,
                    action_id,
                )
                if row is None:
                    return {"status": "not_found", "should_execute": False}
                if row["user_id"] != user_id:
                    return {"status": "forbidden", "should_execute": False}
                status = row["status"]
                if status == "pending" and row["expires_at"] <= await connection.fetchval(
                    "SELECT NOW()"
                ):
                    await connection.execute(
                        """
                        UPDATE pending_actions
                        SET status = 'expired'
                        WHERE action_id = $1::uuid
                        """,
                        action_id,
                    )
                    await _append_audit_event(
                        connection,
                        session_id=str(row["session_id"]),
                        run_id=str(row["run_id"]),
                        action_id=action_id,
                        event_type="pending_action.expired",
                        tool_name=row["tool_name"],
                        status="expired",
                        safe_metadata={},
                    )
                    return {"status": "expired", "should_execute": False}
                if status == "pending":
                    await connection.execute(
                        """
                        UPDATE pending_actions
                        SET status = 'approved', approved_at = NOW()
                        WHERE action_id = $1::uuid
                        """,
                        action_id,
                    )
                    await _append_audit_event(
                        connection,
                        session_id=str(row["session_id"]),
                        run_id=str(row["run_id"]),
                        action_id=action_id,
                        event_type="pending_action.approved",
                        tool_name=row["tool_name"],
                        status="approved",
                        safe_metadata={},
                    )
                    status = "approved"
                return {
                    "status": status,
                    "should_execute": status == "approved",
                    "tool_name": row["tool_name"],
                    "run_id": str(row["run_id"]),
                    "session_id": str(row["session_id"]),
                }
    except Exception as error:
        raise PersistenceError("Could not approve the pending action.") from error


async def claim_pending_action_execution(
    *,
    action_id: str,
    user_id: str,
) -> dict[str, Any]:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT action_id, session_id, run_id, user_id, tool_name,
                           risk_level, status, arguments_json
                    FROM pending_actions
                    WHERE action_id = $1::uuid
                    FOR UPDATE
                    """,
                    action_id,
                )
                if row is None:
                    return {"status": "not_found", "should_execute": False}
                if row["user_id"] != user_id:
                    return {"status": "forbidden", "should_execute": False}
                if row["status"] == "executed":
                    return {"status": "executed", "should_execute": False}
                if row["status"] != "approved":
                    return {"status": row["status"], "should_execute": False}
                await connection.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'executing'
                    WHERE action_id = $1::uuid
                    """,
                    action_id,
                )
                await _append_audit_event(
                    connection,
                    session_id=str(row["session_id"]),
                    run_id=str(row["run_id"]),
                    action_id=action_id,
                    event_type="pending_action.execution_started",
                    tool_name=row["tool_name"],
                    status="executing",
                    safe_metadata={},
                )
                arguments = row["arguments_json"]
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                return {
                    "status": "executing",
                    "should_execute": True,
                    "tool_name": row["tool_name"],
                    "session_id": str(row["session_id"]),
                    "run_id": str(row["run_id"]),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                }
    except Exception as error:
        raise PersistenceError("Could not claim the pending action.") from error


async def complete_pending_action(
    *,
    action_id: str,
    user_id: str,
) -> dict[str, Any]:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT session_id, run_id, user_id, tool_name, status
                    FROM pending_actions
                    WHERE action_id = $1::uuid
                    FOR UPDATE
                    """,
                    action_id,
                )
                if row is None:
                    return {"status": "not_found"}
                if row["user_id"] != user_id:
                    return {"status": "forbidden"}
                if row["status"] == "executed":
                    return {"status": "executed"}
                if row["status"] != "executing":
                    return {"status": row["status"]}
                await connection.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'executed', executed_at = NOW()
                    WHERE action_id = $1::uuid
                    """,
                    action_id,
                )
                await _append_audit_event(
                    connection,
                    session_id=str(row["session_id"]),
                    run_id=str(row["run_id"]),
                    action_id=action_id,
                    event_type="pending_action.executed",
                    tool_name=row["tool_name"],
                    status="executed",
                    safe_metadata={"execution_count": 1},
                )
                return {"status": "executed"}
    except Exception as error:
        raise PersistenceError("Could not complete the pending action.") from error


async def reject_pending_action(
    *,
    action_id: str,
    user_id: str,
) -> dict[str, Any]:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT session_id, run_id, user_id, tool_name, status
                    FROM pending_actions
                    WHERE action_id = $1::uuid
                    FOR UPDATE
                    """,
                    action_id,
                )
                if row is None:
                    return {"status": "not_found"}
                if row["user_id"] != user_id:
                    return {"status": "forbidden"}
                if row["status"] == "pending":
                    await connection.execute(
                        """
                        UPDATE pending_actions
                        SET status = 'rejected', rejected_at = NOW()
                        WHERE action_id = $1::uuid
                        """,
                        action_id,
                    )
                    await _append_audit_event(
                        connection,
                        session_id=str(row["session_id"]),
                        run_id=str(row["run_id"]),
                        action_id=action_id,
                        event_type="pending_action.rejected",
                        tool_name=row["tool_name"],
                        status="rejected",
                        safe_metadata={},
                    )
                    return {"status": "rejected"}
                return {"status": row["status"]}
    except Exception as error:
        raise PersistenceError("Could not reject the pending action.") from error


async def verify_audit_chain() -> dict[str, Any]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT event_id, session_id, run_id, action_id, event_type,
                   tool_name, status, safe_metadata, previous_hash, event_hash
            FROM audit_events
            ORDER BY event_id ASC
            """
        )
    except Exception as error:
        raise PersistenceError("Could not read the audit chain.") from error
    previous_hash: str | None = None
    for row in rows:
        safe_metadata = row["safe_metadata"]
        if isinstance(safe_metadata, str):
            safe_metadata = json.loads(safe_metadata)
        payload = {
            "session_id": str(row["session_id"]) if row["session_id"] else None,
            "run_id": str(row["run_id"]) if row["run_id"] else None,
            "action_id": str(row["action_id"]) if row["action_id"] else None,
            "event_type": row["event_type"],
            "tool_name": row["tool_name"],
            "status": row["status"],
            "safe_metadata": safe_metadata or {},
            "previous_hash": previous_hash,
        }
        expected = hashlib.sha256(
            ((
                previous_hash or ""
            ) + _canonical_json(payload)).encode("utf-8")
        ).hexdigest()
        if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
            return {
                "status": "ERROR",
                "verified": False,
                "event_count": len(rows),
                "safe_error_code": "AUDIT_CHAIN_MISMATCH",
            }
        previous_hash = row["event_hash"]
    return {
        "status": "READY",
        "verified": True,
        "event_count": len(rows),
        "safe_error_code": None,
    }


async def doctor_storage_health() -> dict[str, Any]:
    pool = await _get_pool()
    try:
        row = await pool.fetchrow(
            """
            SELECT
                current_setting('server_version') AS postgres_version,
                EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'vector'
                ) AS pgvector_available,
                (SELECT COUNT(*)::int FROM pending_actions) AS pending_actions,
                (SELECT COUNT(*)::int FROM audit_events) AS audit_events,
                (SELECT COUNT(*)::int FROM agent_run_checkpoints) AS run_checkpoints,
                to_tsvector('simple', 'health check') @@
                    plainto_tsquery('simple', 'health') AS fts_healthy,
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'document_chunks'
                      AND column_name = 'embedding'
                ) AS vector_column_available
            """
        )
    except Exception as error:
        raise PersistenceError("Could not check storage health.") from error
    return dict(row)


async def find_document_by_hash(file_hash: str) -> dict[str, Any] | None:
    pool = await _get_pool()
    try:
        row = await pool.fetchrow(
            """
            SELECT d.document_id, d.filename, d.status, COUNT(c.chunk_id)::int AS chunk_count
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.document_id
            WHERE d.file_hash = $1
            GROUP BY d.document_id, d.filename, d.status
            LIMIT 1
            """,
            file_hash,
        )
    except Exception as error:
        raise PersistenceError("Could not check for a duplicate document.") from error
    return dict(row) if row is not None else None


async def store_document(
    *,
    document_id: str,
    filename: str,
    mime_type: str | None,
    file_hash: str,
    status: str,
    chunks: Sequence[Any],
) -> None:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO documents (
                        document_id,
                        filename,
                        mime_type,
                        source_type,
                        file_hash,
                        status
                    )
                    VALUES ($1::uuid, $2, $3, 'upload', $4, $5)
                    """,
                    document_id,
                    filename,
                    mime_type,
                    file_hash,
                    status,
                )
                if chunks:
                    await connection.executemany(
                        """
                        INSERT INTO document_chunks (
                            document_id,
                            chunk_index,
                            page_number,
                            content,
                            metadata
                        )
                        VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
                        """,
                        [
                            (
                                document_id,
                                chunk.chunk_index,
                                chunk.page_number,
                                chunk.content,
                                json.dumps(chunk.metadata, separators=(",", ":")),
                            )
                            for chunk in chunks
                        ],
                    )
    except Exception as error:
        raise PersistenceError("Could not store the uploaded document.") from error


async def update_document_embedding_status(
    *,
    document_id: str,
    status: str,
    embedding_model: str | None,
    embedding_dimension: int | None,
    embedding_version: str | None,
) -> None:
    pool = await _get_pool()
    try:
        await pool.execute(
            """
            UPDATE documents
            SET status = $2,
                embedding_model = $3,
                embedding_dimension = $4,
                embedding_version = $5,
                updated_at = NOW()
            WHERE document_id = $1::uuid
            """,
            document_id,
            status,
            embedding_model,
            embedding_dimension,
            embedding_version,
        )
    except Exception as error:
        raise PersistenceError("Could not update document embedding status.") from error


async def store_document_embeddings(
    *,
    document_id: str,
    embeddings: Sequence[tuple[int, str]],
    embedding_model: str,
    embedding_dimension: int,
    embedding_version: str,
) -> None:
    pool = await _get_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(
                    """
                    UPDATE document_chunks
                    SET embedding = $2::vector
                    WHERE document_id = $1::uuid AND chunk_index = $3
                    """,
                    [
                        (document_id, vector, chunk_index)
                        for chunk_index, vector in embeddings
                    ],
                )
                await connection.execute(
                    """
                    UPDATE documents
                    SET status = 'ready',
                        embedding_model = $2,
                        embedding_dimension = $3,
                        embedding_version = $4,
                        updated_at = NOW()
                    WHERE document_id = $1::uuid
                    """,
                    document_id,
                    embedding_model,
                    embedding_dimension,
                    embedding_version,
                )
    except Exception as error:
        raise PersistenceError("Could not store document embeddings.") from error


async def search_fts_document_chunks(query: str, top_k: int) -> list[dict[str, Any]]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT
                c.document_id,
                d.filename,
                d.mime_type,
                d.source_type,
                d.file_hash,
                c.chunk_index,
                c.page_number,
                c.content,
                ts_rank_cd(
                    to_tsvector('simple', c.content),
                    plainto_tsquery('simple', $1)
                ) AS rank
            FROM document_chunks c
            JOIN documents d ON d.document_id = c.document_id
            WHERE d.status IN ('ready', 'fts_ready', 'embedding_failed')
              AND to_tsvector('simple', c.content)
                  @@ plainto_tsquery('simple', $1)
            ORDER BY rank DESC, c.document_id, c.chunk_index
            LIMIT $2
            """,
            query,
            top_k,
        )
    except Exception as error:
        raise PersistenceError("Could not search uploaded documents.") from error
    return [dict(row) for row in rows]


async def search_vector_document_chunks(
    *,
    vector: str,
    top_k: int,
    embedding_model: str,
    embedding_dimension: int,
    embedding_version: str,
) -> list[dict[str, Any]]:
    pool = await _get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT
                c.document_id,
                d.filename,
                d.mime_type,
                d.source_type,
                d.file_hash,
                c.chunk_index,
                c.page_number,
                c.content,
                c.embedding <=> $1::vector AS distance
            FROM document_chunks c
            JOIN documents d ON d.document_id = c.document_id
            WHERE d.status = 'ready'
              AND d.embedding_model = $2
              AND d.embedding_dimension = $3
              AND d.embedding_version = $4
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector ASC, c.document_id, c.chunk_index
            LIMIT $5
            """,
            vector,
            embedding_model,
            embedding_dimension,
            embedding_version,
            top_k,
        )
    except Exception as error:
        raise PersistenceError("Could not search document vectors.") from error
    return [dict(row) for row in rows]


async def search_document_chunks(query: str, top_k: int) -> list[dict[str, Any]]:
    return await search_fts_document_chunks(query, top_k)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None