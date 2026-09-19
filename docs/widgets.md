# Writing a widget backend

The fourth plugin seam. The other three ([providers](providers.md)) swap what
fills the terminal's own surfaces; this one adds **new tiles** to the Markets
board without writing any frontend code. A widget backend is any HTTP server
that answers two kinds of request:

- `GET /widgets.json` — a list of **descriptors**: what each tile is called,
  what shape it is, where its data lives, how often it moves.
- `GET <endpoint>` — the tile's **data**, as JSON.

The terminal renders the data with its own primitives, in its own styling.
The descriptor says *what* the tile is — a table, a metrics list — never
*how it looks*, and nothing a backend serves is ever executed or interpreted
as markup: every value is coerced to a capped plain scalar on the server
(`alphadesk/extwidgets.py`) before the frontend sees it. This is the same
posture the news pipeline takes with external text, applied to tiles.

The idea is adopted from OpenBB's Workspace widget architecture (opened
along with the rest of their suite in August 2026), narrowed to fit this
terminal's rules.

## Try it in two minutes

A complete backend ships in [examples/widget_backend.py](examples/widget_backend.py):

```bash
python docs/examples/widget_backend.py
```

Then point the terminal at it and restart:

```ini
ALPHADESK_WIDGET_BACKENDS=http://127.0.0.1:9800
```

Two tiles appear at the bottom of the Markets board: a symbol-scoped table
that follows the strip's marked chip, and a board-independent metrics list.

## The descriptor

```json
{
  "id": "short-interest",
  "type": "table",
  "title": "Short interest",
  "subtitle": "finra, twice monthly",
  "endpoint": "/short",
  "params": ["symbol"],
  "refresh_s": 60,
  "span": 6,
  "columns": [
    {"key": "date",      "label": "Settlement"},
    {"key": "shares",    "label": "Shares short", "align": "right"},
    {"key": "pct_float", "label": "% float",      "align": "right"}
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | Stable slug, unique within your backend. |
| `type` | `table` or `metrics`. Nothing else renders in v1 — an unknown type is dropped with the reason logged, never rendered half-working. |
| `title` | The tile's name. Required. |
| `subtitle` | The footnote beside the name. Say where the data comes from. |
| `endpoint` | Absolute path on *your* server. The terminal's backend fetches it — the browser never talks to you directly, so there is no CORS to configure. |
| `params` | Request parameters you want. v1 vocabulary: `symbol` — declare it and the terminal appends `?symbol=NVDA` (the strip's marked chip) and re-fetches when the board changes. Anything else is stripped, with a log line saying so. |
| `refresh_s` | How often the tile re-polls. Clamped to [15, 3600] — you know how fast your data moves; the terminal bounds the claim. |
| `span` | Grid width on the 12-column board, clamped to [3, 12]. |
| `columns` | Tables only, required there, at most 8. `align: "right"` also formats the cell as a number. |

## The data

For a `table`:

```json
{"rows": [{"date": "2026-08-15", "shares": 61240000, "pct_float": 2.61}]}
```

Only declared column keys leave the server (at most 200 rows); numbers stay
numbers so the terminal can format them, everything else becomes capped plain
text. For `metrics`:

```json
{"metrics": [{"label": "Names on review", "value": 7}]}
```

At most 40 rows, same coercion.

## The contract, in one list

- **Declarative only.** No markup, no scripts, no styling, no iframes — a
  descriptor that asks for one is dropped. If your feature needs real UI, it
  is a fork of the frontend, not a widget.
- **Invalid descriptors are dropped, with the reason logged** on the
  terminal's server. Watch its log while developing.
- **A dead backend degrades, never breaks.** Descriptors are cached five
  minutes and served through an outage; each tile's data failure renders in
  that tile alone, with the reason.
- **Responses are capped** at 256KB and 8 seconds. Stay far under both.
- Multiple backends: comma-separate them in `ALPHADESK_WIDGET_BACKENDS`.
  Tile identity is per-backend, so ids only need to be unique within yours.
