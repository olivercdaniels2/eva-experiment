"""HTTP wrapper so Eva can run on a free Render web service.

Render's free tier has no background workers, and free web services sleep after
~15 minutes idle. So: a tiny HTTP server whose request handling is the wake
signal. The console pings /wake after inserting an enquiry, which boots the
service (cold start ~30-60s) and drains the inbox. A background thread also
polls while the service happens to be awake, so replies to an active thread are
immediate.

Endpoints:
  GET  /        health + status JSON
  POST /wake    drain the inbox now, return what was processed
  GET  /wake    same (so it can be triggered from a browser or uptime pinger)
"""

import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import main as worker
from .mailbox import get_mailbox

_lock = threading.Lock()
_stats = {"started_at": time.time(), "processed": 0, "errors": 0, "last_run": None,
          "last_result": None}


def drain_inbox() -> dict:
    """Process every unread inbound message. Serialised: one drain at a time."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "a drain is already running"}
    try:
        mailbox = get_mailbox()
        results = []
        for msg in mailbox.fetch_unprocessed():
            try:
                worker.process(mailbox, msg)
                _stats["processed"] += 1
                results.append({"id": msg.id, "status": "replied"})
            except Exception as exc:
                traceback.print_exc()
                _stats["errors"] += 1
                mailbox.mark(msg.id, "error")
                results.append({"id": msg.id, "status": "error", "error": str(exc)})
        _stats["last_run"] = time.time()
        _stats["last_result"] = results
        return {"processed": len(results), "results": results}
    finally:
        _lock.release()


def poll_loop():
    """Keep draining while the service is awake; Render may sleep us any time."""
    poll = int(os.environ.get("POLL_SECONDS", "10"))
    while True:
        try:
            drain_inbox()
        except Exception:
            traceback.print_exc()
        time.sleep(poll)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # The console is served from elsewhere (file:// or a static site).
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.startswith("/wake"):
            self._send(200, drain_inbox())
        else:
            self._send(200, {
                "service": "eva-enquiry-agent", "status": "awake",
                "uptime_seconds": round(time.time() - _stats["started_at"]),
                "processed": _stats["processed"], "errors": _stats["errors"],
                "last_run": _stats["last_run"], "last_result": _stats["last_result"],
            })

    def do_POST(self):
        if self.path.startswith("/wake"):
            self._send(200, drain_inbox())
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print(f"[http] {fmt % args}")


def run():
    worker._load_env_file()
    port = int(os.environ.get("PORT", "10000"))
    threading.Thread(target=poll_loop, daemon=True).start()
    print(f"[eva] web service listening on :{port}, poll thread running")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    run()
