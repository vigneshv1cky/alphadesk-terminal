"""WHAT AGENTS ASK AND WHAT THEY GET BACK (2026-10-03).

Every tool call through the agent door is written to a table: which tool, with
what arguments, how long it took, and how it ended. A task id and a one-line
intent, when the caller sends them as the request headers X-Agent-Task and
X-Agent-Intent, are kept beside each call so a reader can see WHY a run of
calls was made. Without them, calls from one token close together in time are
grouped as one task in the report.

Read it with `python -m alphadesk.main agent-usage` or GET /api/agent/usage.
It shows what to fix: tools that never get called, tools that return nothing
or fail (and for which kind of symbol), slow ones, and the same chain of calls
repeated — which is a tool that should exist.

NEVER SEEN HERE: tokens, keys, the agent's reasoning or its final answer. A
failure to write a row must never fail the tool call it describes.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

#: Who is calling and why, set by the token gate for the length of one request.
_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar("alphadesk_agent_context", default=None)

_ARGS_MAX = 1500
_INTENT_MAX = 300
_TASK_MAX = 64
#: Calls from one token closer together than this are one task when no task id came.
TASK_GAP_S = 60


def clean_header(value: str | None, limit: int) -> str | None:
    """A header value fit for storing: printable, trimmed, bounded."""
    text = re.sub(r"[^\x20-\x7e -￿]", "", value or "").strip()
    return text[:limit] or None


def set_context(token_id: str | None, task_id: str | None, intent: str | None, client: str | None = None):
    return _context.set({"token_id": token_id, "task_id": clean_header(task_id, _TASK_MAX),
                         "intent": clean_header(intent, _INTENT_MAX), "client": clean_header(client, 80)})


def reset_context(token) -> None:
    _context.reset(token)


def context() -> dict:
    return _context.get() or {}


_EMPTY_KEYS = ("rows", "articles", "posts", "candidates", "results", "stories", "holders", "trades", "filings",
               "reports", "symbols", "peers", "funds")


def classify(result, exc: BaseException | None) -> tuple[str, str | None]:
    """(outcome, kind). outcome is answered, empty, incomplete or error."""
    if exc is not None:
        text = str(exc).lower()
        name = type(exc).__name__
        if name == "NeedsKey":
            if "returned nothing" in text:
                return "error", "no_coverage"
            if "plan on" in text:
                return "error", "plan_limit"
            if "could not be read" in text:
                return "error", "vendor_failed"
            return "error", "no_key"
        if isinstance(exc, ValueError):
            return "error", "no_data" if text.startswith("no ") or "not available" in text else "rejected"
        return "error", name[:40]
    if isinstance(result, dict):
        if result.get("unavailable") or result.get("failed") or result.get("reliable") is False:
            return "incomplete", None
        if result.get("count") == 0:
            return "empty", None
        for key in _EMPTY_KEYS:
            if key in result and isinstance(result[key], list) and not result[key]:
                return "empty", None
    elif isinstance(result, (list, tuple)) and not result:
        return "empty", None
    elif result is None:
        return "empty", None
    return "answered", None


def _args_text(args: dict) -> str:
    try:
        text = json.dumps(args, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(args)
    return text[:_ARGS_MAX]


def record(tool: str, args: dict, ms: float, result, exc: BaseException | None) -> None:
    """File one call. Never raises."""
    try:
        from alphadesk.identity import request_user
        from alphadesk.ledger import store
        outcome, kind = classify(result, exc)
        try:
            size = len(json.dumps(result, default=str)) if result is not None else 0
        except Exception:
            size = 0
        ctx = context()
        store.save_agent_call({
            "id": uuid.uuid4().hex, "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "token_id": ctx.get("token_id"), "user_id": request_user(), "task_id": ctx.get("task_id"),
            "intent": ctx.get("intent"), "tool": tool, "args": _args_text(args), "ms": int(ms),
            "outcome": outcome, "error_kind": kind, "bytes": size})
    except Exception as exc2:                                    # a log must never break a tool
        log.debug("agent call not logged: %s", exc2)


_RATINGS = {"yes": 1, "useful": 1, "partly": 0, "no": -1, "not_useful": -1, 1: 1, 0: 0, -1: -1}


def record_feedback(body: dict) -> dict:
    """File a caller's verdict on a result. Raises ValueError for a body that
    names no rating. `useful` is yes, partly or no (or 1, 0, -1); `tool` and
    `task_id` say which call or task; `note` and `missing` are free text."""
    from alphadesk.ledger import store
    raw = body.get("useful", body.get("rating"))
    key = raw.strip().lower() if isinstance(raw, str) else raw
    if key not in _RATINGS:
        raise ValueError('"useful" must be yes, partly or no')
    ctx = context()
    tool = clean_header(str(body.get("tool") or ""), 60)
    store.save_agent_feedback({
        "id": uuid.uuid4().hex, "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "token_id": ctx.get("token_id"), "task_id": clean_header(str(body.get("task_id") or ctx.get("task_id") or ""), _TASK_MAX),
        "tool": tool, "rating": _RATINGS[key],
        "note": clean_header(str(body.get("note") or ""), 500), "missing": clean_header(str(body.get("missing") or ""), 300)})
    return {"ok": True}


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


def assign_tasks(rows: list[dict]) -> list[dict]:
    """Rows (oldest first) with a `task` key: the caller's task id where it sent
    one, else one id per token per run of calls less than TASK_GAP_S apart."""
    last: dict[str, tuple[datetime, str]] = {}
    out = []
    for r in rows:
        if r.get("task_id"):
            out.append({**r, "task": f"{r.get('token_id') or '-'}:{r['task_id']}"})
            continue
        at = datetime.fromisoformat(r["at"])
        tok = r.get("token_id") or "-"
        prev = last.get(tok)
        if prev is None or (at - prev[0]).total_seconds() > TASK_GAP_S:
            task = f"{tok}@{r['at'][:19]}"
        else:
            task = prev[1]
        last[tok] = (at, task)
        out.append({**r, "task": task})
    return out


def summarize(rows: list[dict], known_tools: list[str] | None = None, feedback: list[dict] | None = None) -> dict:
    """The report over `rows` (oldest first)."""
    rows = assign_tasks(rows)
    by_tool: dict[str, list[dict]] = {}
    for r in rows:
        by_tool.setdefault(r["tool"], []).append(r)
    tools = []
    for name, calls in by_tool.items():
        n = len(calls)
        count = lambda o: sum(1 for c in calls if c["outcome"] == o)  # noqa: E731
        kinds: dict[str, int] = {}
        for c in calls:
            if c.get("error_kind"):
                kinds[c["error_kind"]] = kinds.get(c["error_kind"], 0) + 1
        ms = [c["ms"] for c in calls if c.get("ms") is not None]
        tools.append({"tool": name, "calls": n, "answered_pct": _pct(count("answered"), n),
                      "empty_pct": _pct(count("empty"), n), "incomplete_pct": _pct(count("incomplete"), n),
                      "error_pct": _pct(count("error"), n), "error_kinds": kinds,
                      "p50_ms": _percentile(ms, .5), "p95_ms": _percentile(ms, .95),
                      "median_bytes": _percentile([c["bytes"] for c in calls if c.get("bytes") is not None], .5)})
        said = [f["rating"] for f in (feedback or []) if f.get("tool") == name]
        tools[-1]["feedback"] = ({"n": len(said), "useful": said.count(1), "partly": said.count(0), "not_useful": said.count(-1)}
                                 if said else None)
    tools.sort(key=lambda t: -t["calls"])
    # The chains: each task's tools in order, collapsed where a tool repeats back to back.
    tasks: dict[str, list[dict]] = {}
    for r in rows:
        tasks.setdefault(r["task"], []).append(r)
    chains: dict[str, int] = {}
    for calls in tasks.values():
        seq: list[str] = []
        for c in calls:
            if not seq or seq[-1] != c["tool"]:
                seq.append(c["tool"])
        if len(seq) >= 3:
            key = " → ".join(seq[:8])
            chains[key] = chains.get(key, 0) + 1
    repeated = sorted(((k, v) for k, v in chains.items() if v >= 2), key=lambda kv: -kv[1])[:10]
    used = set(by_tool)
    return {
        "calls": len(rows), "tasks": len(tasks),
        "from": rows[0]["at"] if rows else None, "to": rows[-1]["at"] if rows else None,
        "tools": tools,
        "never_called": sorted(set(known_tools or []) - used),
        "worst": [t["tool"] for t in sorted(tools, key=lambda t: -(t["error_pct"] + t["empty_pct"] + t["incomplete_pct"]))
                  if t["calls"] >= 3 and (t["error_pct"] + t["empty_pct"] + t["incomplete_pct"]) >= 30][:8],
        "slowest": [t["tool"] for t in sorted(tools, key=lambda t: -(t["p95_ms"] or 0)) if (t["p95_ms"] or 0) >= 3000][:8],
        "repeated_chains": [{"chain": k, "times": v} for k, v in repeated],
        "intents": sorted({r["intent"] for r in rows if r.get("intent")})[:20],
        "feedback": {
            "given": len(feedback or []),
            "not_useful_tools": sorted({f["tool"] for f in (feedback or []) if f.get("tool") and f["rating"] == -1}),
            # What agents said they were missing, newest first: the best list of what to build next.
            "missing": [{"at": f["at"], "tool": f.get("tool"), "missing": f["missing"]}
                        for f in reversed(feedback or []) if f.get("missing")][:20],
            "notes": [{"at": f["at"], "tool": f.get("tool"), "rating": f["rating"], "note": f["note"]}
                      for f in reversed(feedback or []) if f.get("note")][:20],
        },
    }


def report(days: int = 30) -> dict:
    """The summary over the last `days`."""
    from alphadesk.ledger import store
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 3650)))).isoformat()
    try:
        from alphadesk import mcp_server
        import asyncio
        known = [t.name for t in asyncio.run(mcp_server.mcp.list_tools())]
    except Exception:
        known = []
    return {"days": days, **summarize(store.agent_calls_since(since), known, store.agent_feedback_since(since))}
