"""Declarative external widgets — the fourth plugin seam.

The other three seams (LLM, news, prices) swap what fills the terminal's own
surfaces. This one adds NEW tiles without shipping frontend code: a widget
backend is any HTTP server that serves a descriptor list at
`GET <base>/widgets.json` and JSON data at the endpoints those descriptors
name. The terminal renders the data with its own primitives — the descriptor
says WHAT the tile is (a table, a metrics list) and never HOW it looks.

Modeled on OpenBB's Workspace widgets (adopted 2026-09-01, after their suite
went open source), narrowed to fit this terminal's rules:

- **Declarative only, never executable.** A backend contributes data and a
  shape. No remote markup, no remote script, no styling hooks. Every value is
  coerced to a plain scalar and length-capped here, before the frontend sees
  it — the same posture wrap_data() takes with news text: external content is
  data, not instructions.
- **Broken descriptors are DROPPED, with the reason logged** — never rendered
  half-working. Same rule the attribution surfaces follow.
- **The reader's board stays the scope.** A descriptor may declare it takes
  the active symbol; the terminal then passes ?symbol= and re-fetches when
  the board changes. No other request parameter exists in v1.

Configuration: `ALPHADESK_WIDGET_BACKENDS` — comma-separated base URLs.
Absent (the default) this whole module is inert: no fetches, no tiles.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("alphadesk.extwidgets")

# One descriptor fetch per backend per this many seconds. Descriptors change
# when the backend redeploys, not per request.
_DESCRIPTOR_TTL_S = 300.0

# A data response larger than this is a bug or an attack, not a tile.
_MAX_BYTES = 262_144

_TIMEOUT_S = 8.0

# The whole v1 parameter vocabulary. A descriptor asking for anything else is
# asking this terminal to forward state it does not have or should not send.
_ALLOWED_PARAMS = {"symbol"}

_ALLOWED_TYPES = {"table", "metrics"}

_MAX_WIDGETS_PER_BACKEND = 12
_MAX_COLUMNS = 8
_MAX_ROWS = 200
_MAX_METRICS = 40
_MAX_STR = 300

_desc_cache: dict[str, tuple[float, list[dict]]] = {}


def backends() -> list[str]:
    raw = os.environ.get("ALPHADESK_WIDGET_BACKENDS", "")
    out = []
    for part in raw.split(","):
        base = part.strip().rstrip("/")
        if base.startswith(("http://", "https://")):
            out.append(base)
        elif base:
            log.warning("widget backend %r ignored: not an http(s) URL", base)
    return out


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "AlphaDesk-widgets"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = resp.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError(f"response exceeds {_MAX_BYTES} bytes")
    return json.loads(body)


def _clean_str(v: Any, cap: int = _MAX_STR) -> str:
    return str(v)[:cap]


def _validate_descriptor(raw: Any, backend_index: int) -> dict | None:
    """One descriptor, checked field by field. Returns the cleaned form or
    None — an invalid descriptor is dropped with its reason logged, never
    rendered in a degraded state."""
    if not isinstance(raw, dict):
        log.warning("backend %d: descriptor is not an object", backend_index)
        return None
    wid = raw.get("id")
    if not isinstance(wid, str) or not wid or len(wid) > 64:
        log.warning("backend %d: descriptor with missing/oversized id dropped", backend_index)
        return None
    wtype = raw.get("type")
    if wtype not in _ALLOWED_TYPES:
        log.warning("backend %d: widget %r dropped: unknown type %r "
                    "(v1 renders: %s)", backend_index, wid, wtype,
                    ", ".join(sorted(_ALLOWED_TYPES)))
        return None
    endpoint = raw.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.startswith("/") or ".." in endpoint:
        log.warning("backend %d: widget %r dropped: endpoint must be an "
                    "absolute path on the backend", backend_index, wid)
        return None
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        log.warning("backend %d: widget %r dropped: a tile must be named", backend_index, wid)
        return None

    params = raw.get("params", [])
    if not isinstance(params, list):
        params = []
    unknown = [p for p in params if p not in _ALLOWED_PARAMS]
    if unknown:
        # Not fatal: the widget still works scoped to nothing. The backend
        # author sees why their parameter never arrives.
        log.warning("backend %d: widget %r: ignoring unsupported params %s",
                    backend_index, wid, unknown)
    params = [p for p in params if p in _ALLOWED_PARAMS]

    try:
        refresh_s = int(raw.get("refresh_s", 60))
    except (TypeError, ValueError):
        refresh_s = 60
    refresh_s = max(15, min(3600, refresh_s))

    try:
        span = int(raw.get("span", 4))
    except (TypeError, ValueError):
        span = 4
    span = max(3, min(12, span))

    columns: list[dict] = []
    if wtype == "table":
        raw_cols = raw.get("columns")
        if not isinstance(raw_cols, list) or not raw_cols:
            log.warning("backend %d: widget %r dropped: a table declares its "
                        "columns", backend_index, wid)
            return None
        for c in raw_cols[:_MAX_COLUMNS]:
            if not isinstance(c, dict) or not isinstance(c.get("key"), str):
                continue
            columns.append({
                "key": _clean_str(c["key"], 64),
                "label": _clean_str(c.get("label", c["key"]), 64),
                "align": "right" if c.get("align") == "right" else "left",
            })
        if not columns:
            log.warning("backend %d: widget %r dropped: no usable columns",
                        backend_index, wid)
            return None

    return {
        # Backend index + declared id: unique across backends without trusting
        # ids to be globally unique, stable across descriptor refreshes.
        "uid": f"ext{backend_index}-{wid}",
        "backend": backend_index,
        "id": wid,
        "type": wtype,
        "title": _clean_str(title.strip(), 80),
        "subtitle": _clean_str(raw.get("subtitle", ""), 120),
        "endpoint": endpoint,
        "params": params,
        "refresh_s": refresh_s,
        "span": span,
        "columns": columns,
    }


def list_widgets(refresh: bool = False) -> list[dict]:
    """Every valid descriptor across the configured backends, cached briefly.

    A backend that is down contributes nothing this round — its tiles vanish
    rather than erroring the board, the same degradation a dead provider
    gets."""
    out: list[dict] = []
    for i, base in enumerate(backends()):
        now = time.monotonic()
        cached = _desc_cache.get(base)
        if cached and not refresh and now - cached[0] < _DESCRIPTOR_TTL_S:
            out.extend(cached[1])
            continue
        try:
            raw = _fetch_json(f"{base}/widgets.json")
        except (urllib.error.URLError, ValueError, json.JSONDecodeError, OSError) as exc:
            log.warning("widget backend %s unreachable: %s", base, exc)
            # Keep serving the last good descriptors through an outage —
            # the tile's DATA fetch will surface the failure per-tile.
            if cached:
                out.extend(cached[1])
            continue
        if not isinstance(raw, list):
            log.warning("widget backend %s: widgets.json is not a list", base)
            continue
        cleaned = [d for d in (
            _validate_descriptor(r, i) for r in raw[:_MAX_WIDGETS_PER_BACKEND]
        ) if d]
        _desc_cache[base] = (now, cleaned)
        out.extend(cleaned)
    return out


def _clean_rows(payload: Any, columns: list[dict]) -> list[dict]:
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    keys = [c["key"] for c in columns]
    out = []
    for r in rows[:_MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        row = {}
        for k in keys:
            v = r.get(k)
            # Numbers stay numbers so the frontend can format them; anything
            # else becomes capped plain text. Nothing structured survives.
            row[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) \
                else _clean_str(v) if v is not None else None
        out.append(row)
    return out


def _clean_metrics(payload: Any) -> list[dict]:
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, list):
        return []
    out = []
    for m in metrics[:_MAX_METRICS]:
        if not isinstance(m, dict):
            continue
        label = m.get("label")
        if not isinstance(label, str) or not label:
            continue
        v = m.get("value")
        out.append({
            "label": _clean_str(label, 64),
            "value": v if isinstance(v, (int, float)) and not isinstance(v, bool)
            else _clean_str(v) if v is not None else None,
        })
    return out


def fetch_data(uid: str, symbol: str | None = None) -> dict:
    """The tile's data, fetched from its backend and cleaned to plain scalars.

    Raises LookupError for a uid no current descriptor claims — the caller
    turns that into a 404 rather than proxying arbitrary URLs."""
    desc = next((d for d in list_widgets() if d["uid"] == uid), None)
    if desc is None:
        raise LookupError(uid)
    base = backends()[desc["backend"]]
    url = f"{base}{desc['endpoint']}"
    if "symbol" in desc["params"] and symbol:
        from urllib.parse import quote
        url += f"?symbol={quote(symbol.upper()[:12])}"
    payload = _fetch_json(url)
    if desc["type"] == "table":
        return {"uid": uid, "type": "table", "rows": _clean_rows(payload, desc["columns"])}
    return {"uid": uid, "type": "metrics", "metrics": _clean_metrics(payload)}
