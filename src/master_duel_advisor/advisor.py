from __future__ import annotations

import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>Master Duel Advisor</title>
<style>body{font:16px system-ui;background:#101927;color:#edf4ff;max-width:1100px;margin:30px auto}section{padding:20px;border:1px solid #405472;border-radius:12px;margin:16px 0}pre{white-space:pre-wrap}h1{color:#74ddc1}</style>
<h1>Master Duel Advisor</h1><p>観測専用 · 操作はプレイヤーが行います · 部分的なルールによる候補表示</p>
<section><h2>Recommended Action</h2><pre id="advice">Waiting for observations</pre></section>
<section><h2>Current State</h2><pre id="state"></pre></section>
<section><h2>Recognition Status / Metrics</h2><pre id="status"></pre></section>
<script>async function refresh(){try{let s=await (await fetch('/state',{cache:'no-store'})).json();document.getElementById('advice').textContent=JSON.stringify(s.recommendation,null,2);document.getElementById('state').textContent=JSON.stringify(s.state,null,2);document.getElementById('status').textContent=JSON.stringify({error:s.error,metrics:s.metrics,events:s.events},null,2)}catch(e){document.getElementById('status').textContent='Connection unavailable'}}setInterval(refresh,400);refresh()</script></html>"""


class SnapshotStore:
    def __init__(self, max_age: float = 1.5):
        self.lock = threading.Lock()
        self.max_age = max_age
        self.updated: float | None = None
        self.snapshot = {"state": None, "events": [], "error": None, "metrics": {}, "recommendation": {"action": None, "target": None, "confidence": 0, "reason": "Waiting for capture", "recognition_status": "unknown"}}

    def update(self, snapshot: dict):
        with self.lock:
            self.snapshot = copy.deepcopy(snapshot)
            self.updated = time.monotonic()

    def get(self) -> dict:
        with self.lock:
            result = copy.deepcopy(self.snapshot)
            if self.updated is not None and time.monotonic()-self.updated > self.max_age:
                result["recommendation"] = {"action": None, "target": None, "confidence": 0, "reason": "Capture is stale or stopped; wait for a new frame", "recognition_status": "stale"}
            return result


def start_server(store: SnapshotStore, port: int = 8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body, content_type = HTML.encode("utf-8"), "text/html; charset=utf-8"
            elif self.path == "/state":
                body, content_type = json.dumps(store.get(), ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
