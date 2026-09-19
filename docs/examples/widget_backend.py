"""A complete AlphaDesk widget backend, ~40 lines. Serves two tiles."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

WIDGETS = [
    {
        "id": "short-interest", "type": "table", "title": "Short interest",
        "subtitle": "example backend", "endpoint": "/short", "params": ["symbol"],
        "refresh_s": 60, "span": 6,
        "columns": [
            {"key": "date", "label": "Settlement"},
            {"key": "shares", "label": "Shares short", "align": "right"},
            {"key": "pct_float", "label": "% float", "align": "right"},
        ],
    },
    {
        "id": "desk-notes", "type": "metrics", "title": "Desk numbers",
        "subtitle": "example backend", "endpoint": "/notes", "refresh_s": 120, "span": 6,
    },
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/widgets.json":
            body = WIDGETS
        elif u.path == "/short":
            sym = (parse_qs(u.query).get("symbol") or ["?"])[0]
            body = {"rows": [
                {"date": "2026-08-15", "shares": 61_240_000, "pct_float": 2.61},
                {"date": "2026-07-31", "shares": 58_990_000, "pct_float": 2.52},
                {"date": "2026-07-15", "shares": 63_100_000, "pct_float": 2.70},
            ], "symbol": sym}
        elif u.path == "/notes":
            body = {"metrics": [
                {"label": "Desk risk budget", "value": "green"},
                {"label": "Names on review", "value": 7},
                {"label": "Next rebalance", "value": "2026-09-15"},
            ]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", 9800), Handler).serve_forever()
