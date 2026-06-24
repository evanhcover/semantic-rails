"""Warehouse-adapter base class and limits contract.

Defines :class:`WarehouseAdapter` — the abstract interface every
warehouse adapter implements — and the helpers that translate the
``limits`` dict (``statement_timeout_ms``, ``max_rows``) into adapter
actions. Lives under :mod:`semantic_rails.db_parts` so both
:mod:`semantic_rails.db` (DuckDB) and
:mod:`semantic_rails.db_parts.snowflake` (Snowflake) can implement
the contract without a circular import. The public surface is
re-exported through :mod:`semantic_rails.db`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class WarehouseAdapter(ABC):
    engine: str
    # Whether this adapter actually honors `limits.statement_timeout_ms`
    # at the database boundary. Adapters that can't enforce timeouts at
    # the warehouse level set this to False; the runtime surfaces a
    # `warnings` entry so the caller learns the limit was best-effort.
    # Defaults to False — adapters that can enforce timeouts must
    # explicitly opt in. (DuckDB: False; SnowflakeCliAdapter: True via
    # session-level ALTER SESSION.)
    supports_statement_timeout: bool = False

    @abstractmethod
    def query(self, sql: str, *, limits: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute SQL and return rows.

        `limits` is an optional dict with these recognized keys:

        - `statement_timeout_ms` — abort the query after N ms (best-effort
          per adapter; check `supports_statement_timeout`)
        - `max_rows` — clip the result to N rows (post-fetch fence,
          enforced uniformly across adapters)

        Per-adapter enforcement is best-effort; backends that don't
        support a given knob ignore it. The default semantics are
        documented in `docs/QUERY_API.md` (request "limits" block).
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


def _clip_rows(rows: list[dict[str, Any]], limits: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not limits:
        return rows
    max_rows = limits.get("max_rows")
    if not max_rows:
        return rows
    try:
        cap = int(max_rows)
    except (TypeError, ValueError):
        return rows
    if cap < 0:
        return rows
    if len(rows) <= cap:
        return rows
    return rows[:cap]


def _limit_timeout_seconds(limits: dict[str, Any] | None) -> int:
    if not limits:
        return 0
    raw = limits.get("statement_timeout_ms")
    if raw is None:
        return 0
    try:
        ms = int(raw)
    except (TypeError, ValueError):
        return 0
    if ms <= 0:
        return 0
    return max(1, (ms + 999) // 1000)
