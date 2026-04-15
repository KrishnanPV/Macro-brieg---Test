"""API cost tracking: pricing table, SQLite logging, and query helpers."""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing table  ($ per 1 million tokens)
# Source: QB AI Gateway — docs.prod.ai-gateway.quantumblack.com/models
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI  ─────────────────────────────────────────────────────────────
    # (input $/1M tok, output $/1M tok)
    "gpt-3.5-turbo":                (0.50,   1.50),
    "gpt-3.5-turbo-0125":           (0.50,   1.50),
    "gpt-3.5-turbo-1106":           (1.50,   2.00),
    "gpt-3.5-turbo-16k":            (3.00,   4.00),
    "gpt-4":                        (30.00,  60.00),
    "gpt-4-0314":                   (30.00,  60.00),
    "gpt-4-0613":                   (30.00,  60.00),
    "gpt-4-turbo":                  (10.00,  30.00),
    "gpt-4-turbo-2024-04-09":       (10.00,  30.00),
    "gpt-4-turbo-preview":          (10.00,  30.00),
    "gpt-4-0125-preview":           (10.00,  30.00),
    "gpt-4-1106-preview":           (10.00,  30.00),
    "gpt-4o":                       (2.50,   10.00),
    "gpt-4o-2024-05-13":            (5.00,   15.00),
    "gpt-4o-2024-08-06":            (2.50,   10.00),
    "gpt-4o-2024-11-20":            (2.50,   10.00),
    "gpt-4o-mini":                  (0.15,   0.60),
    "gpt-4o-mini-2024-07-18":       (0.15,   0.60),
    "gpt-4.5-preview":              (75.00,  150.00),
    "gpt-4.5-preview-2025-02-27":   (75.00,  150.00),
    "gpt-4o-search-preview":        (2.50,   10.00),
    "gpt-4o-search-preview-2025-03-11": (2.50, 10.00),
    "gpt-4o-mini-search-preview":   (0.15,   0.60),
    "gpt-4o-mini-search-preview-2025-03-11": (0.15, 0.60),
    "gpt-4.1":                      (2.00,   8.00),
    "gpt-4.1-2025-04-14":           (2.00,   8.00),
    "gpt-4.1-mini":                 (0.40,   1.60),
    "gpt-4.1-mini-2025-04-14":      (0.40,   1.60),
    "gpt-4.1-nano":                 (0.10,   0.40),
    "gpt-4.1-nano-2025-04-14":      (0.10,   0.40),
    # Reasoning models
    "o1-preview":                   (15.00,  60.00),
    "o1-preview-2024-09-12":        (15.00,  60.00),
    "o1":                           (15.00,  60.00),
    "o1-2024-12-17":                (15.00,  60.00),
    "o3-mini":                      (1.10,   4.40),
    "o3-mini-2025-01-31":           (1.10,   4.40),
    "o4-mini":                      (1.10,   4.40),
    "o4-mini-2025-04-16":           (1.10,   4.40),
    "o3":                           (2.00,   8.00),
    "o3-2025-04-16":                (2.00,   8.00),
    # GPT-5 family
    "gpt-5":                        (1.25,   10.00),
    "gpt-5-2025-08-07":             (1.25,   10.00),
    "gpt-5-chat-latest":            (1.25,   10.00),
    "gpt-5.1-2025-11-13":           (1.25,   10.00),
    "gpt-5-mini":                   (0.25,   2.00),
    "gpt-5-mini-2025-08-07":        (0.25,   2.00),
    "gpt-5-nano":                   (0.05,   0.40),
    "gpt-5-nano-2025-08-07":        (0.05,   0.40),
    "gpt-5.2-chat-latest":          (1.75,   14.00),
    "gpt-5.3-chat-latest":          (1.75,   14.00),
    "gpt-5.2-2025-12-11":           (1.75,   14.00),
    "gpt-5.4":                      (2.75,   16.50),
    "gpt-5.4-2026-03-05":           (2.75,   16.50),
    "gpt-5.4-mini":                 (0.825,  4.95),
    "gpt-5.4-mini-2026-03-17":      (0.825,  4.95),
    "gpt-5.4-nano":                 (0.22,   1.375),
    "gpt-5.4-nano-2026-03-17":      (0.22,   1.375),
    "gpt-5-pro-2025-10-06":         (15.00,  120.00),
    # Perplexity  ─────────────────────────────────────────────────────────
    "sonar":                        (1.00,   1.00),
    "sonar-pro":                    (3.00,   15.00),
    "sonar-reasoning-pro":          (2.00,   8.00),
    "sonar-deep-research":          (2.00,   8.00),
    # Anthropic  ──────────────────────────────────────────────────────────
    "claude-3-haiku-20240307":      (0.25,   1.25),
    "claude-haiku-4-5-20251001":    (1.00,   5.00),
    "claude-opus-4-20250514":       (15.00,  75.00),
    "claude-opus-4-1-20250805":     (15.00,  75.00),
    "claude-sonnet-4-20250514":     (3.00,   15.00),
    "claude-sonnet-4-5-20250929":   (3.00,   15.00),
    "claude-sonnet-4-6":            (3.00,   15.00),
    "claude-opus-4-5-20251101":     (5.00,   25.00),
    "claude-opus-4-6":              (5.00,   25.00),
    # Google Vertex AI  ───────────────────────────────────────────────────
    "gemini-2.0-flash-lite":        (0.075,  0.30),
    "gemini-2.0-flash-lite-001":    (0.075,  0.30),
    "gemini-2.0-flash":             (0.15,   0.60),
    "gemini-2.0-flash-001":         (0.15,   0.60),
    "gemini-2.5-flash-lite":        (0.10,   0.40),
    "gemini-2.5-flash":             (0.30,   2.50),
    "gemini-2.5-pro":               (1.25,   10.00),
    "gemini-3-flash-preview":       (0.50,   3.00),
    "gemini-3-pro-preview":         (2.00,   12.00),
    "gemini-3.1-flash-lite-preview": (0.25,  1.50),
    "gemini-3.1-pro-preview":       (2.00,   12.00),
    # Cohere  ─────────────────────────────────────────────────────────────
    "command-nightly":              (1.00,   2.00),
    "command-a-03-2025":            (2.50,   10.00),
    "command-r-plus-08-2024":       (2.50,   10.00),
    "command-r7b-12-2024":          (0.0375, 0.15),
    "command-r-08-2024":            (0.15,   0.60),
    # AWS Bedrock (Llama)  ────────────────────────────────────────────────
    "us.meta.llama4-maverick-17b-instruct-v1:0": (0.24, 0.97),
    "us.meta.llama4-scout-17b-instruct-v1:0":    (0.17, 0.66),
    "us.meta.llama3-3-70b-instruct-v1:0":        (0.72, 0.72),
    "us.meta.llama3-1-70b-instruct-v1:0":        (0.72, 0.72),
    "us.meta.llama3-1-8b-instruct-v1:0":         (0.22, 0.22),
}

# ---------------------------------------------------------------------------
# Pricing lookup with fallback
# ---------------------------------------------------------------------------

def _lookup_pricing(model: str) -> tuple[float, float]:
    """Return (input_cost, output_cost) per 1M tokens for *model*.

    Tries exact match first, then prefix match (longest wins).
    Falls back to (0, 0) if unknown — still logs the call.
    """
    model_lower = model.lower().strip()
    if model_lower in MODEL_PRICING:
        return MODEL_PRICING[model_lower]
    # prefix match: e.g. "gpt-4o-mini-2024-07-18" → "gpt-4o-mini"
    best = ""
    for key in MODEL_PRICING:
        if model_lower.startswith(key) and len(key) > len(best):
            best = key
    if best:
        return MODEL_PRICING[best]
    log.warning("No pricing entry for model %r — cost will be $0", model)
    return (0.0, 0.0)


# ---------------------------------------------------------------------------
# SQLite persistence (sync, WAL mode, thread-safe)
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cost_log.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_log (
                id            TEXT PRIMARY KEY,
                timestamp     TEXT NOT NULL,
                caller        TEXT NOT NULL,
                model         TEXT NOT NULL,
                input_tokens  INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                input_cost    REAL NOT NULL,
                output_cost   REAL NOT NULL,
                total_cost    REAL NOT NULL
            )
        """)
        _conn.commit()
    return _conn


def init_cost_db() -> None:
    """Eagerly create the DB and table at startup."""
    with _lock:
        _get_conn()
    log.info("Cost-tracking DB ready at %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_usage(
    model: str,
    usage: Any,
    caller: str,
) -> None:
    """Log one API call's token usage and computed cost.

    *usage* can be an OpenAI ``Usage`` object (has ``.prompt_tokens`` /
    ``.completion_tokens``) or a dict with those keys.
    """
    if usage is None:
        return

    if isinstance(usage, dict):
        in_tok = usage.get("prompt_tokens", 0) or 0
        out_tok = usage.get("completion_tokens", 0) or 0
    else:
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0

    if in_tok == 0 and out_tok == 0:
        return

    input_price, output_price = _lookup_pricing(model)
    in_cost = in_tok * input_price / 1_000_000
    out_cost = out_tok * output_price / 1_000_000
    total = in_cost + out_cost

    row_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO cost_log "
            "(id, timestamp, caller, model, input_tokens, output_tokens, "
            " input_cost, output_cost, total_cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, ts, caller, model, in_tok, out_tok, in_cost, out_cost, total),
        )
        conn.commit()

    log.info(
        "COST | %-40s | %-20s | in=%6d out=%6d | $%.6f",
        caller, model, in_tok, out_tok, total,
    )


# ---------------------------------------------------------------------------
# Query helpers (used by the dashboard)
# ---------------------------------------------------------------------------

def get_recent_log(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT timestamp, caller, model, input_tokens, output_tokens, "
            "       input_cost, output_cost, total_cost "
            "FROM cost_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_summary() -> dict[str, Any]:
    with _lock:
        conn = _get_conn()

        row = conn.execute(
            "SELECT COUNT(*), "
            "       COALESCE(SUM(input_tokens), 0), "
            "       COALESCE(SUM(output_tokens), 0), "
            "       COALESCE(SUM(total_cost), 0) "
            "FROM cost_log"
        ).fetchone()
        total_calls, total_in, total_out, total_cost = row

        by_model = conn.execute(
            "SELECT model, COUNT(*), "
            "       SUM(input_tokens), SUM(output_tokens), SUM(total_cost) "
            "FROM cost_log GROUP BY model ORDER BY SUM(total_cost) DESC"
        ).fetchall()

        by_caller = conn.execute(
            "SELECT caller, COUNT(*), "
            "       SUM(input_tokens), SUM(output_tokens), SUM(total_cost) "
            "FROM cost_log GROUP BY caller ORDER BY SUM(total_cost) DESC"
        ).fetchall()

    return {
        "total_calls": total_calls,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost": total_cost,
        "by_model": [
            {"model": m, "calls": c, "input_tokens": i, "output_tokens": o, "cost": cost}
            for m, c, i, o, cost in by_model
        ],
        "by_caller": [
            {"caller": cal, "calls": c, "input_tokens": i, "output_tokens": o, "cost": cost}
            for cal, c, i, o, cost in by_caller
        ],
    }
