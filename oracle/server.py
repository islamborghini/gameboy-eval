"""HTTP oracle: SameBoy exposed as a black box.

Wraps `SameBoyCore` behind HTTP so a candidate/agent can observe the reference's output
(framebuffers, audio) without ever seeing SameBoy's source or binary. Shaped like the
candidate ABI: a stateful session (/load, /reset, /set_keys, /run_frame, /framebuffer)
plus a batch /run.

    .venv/bin/python oracle/server.py [--host 0.0.0.0] [--port 8765]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sameboy import SameBoyCore  # noqa: E402

_lock = threading.Lock()
_core: SameBoyCore | None = None


def _get_core() -> SameBoyCore:
    global _core
    if _core is None:
        _core = SameBoyCore()
    return _core


def _png_b64(frame: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(frame, "RGBA").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path.split("?")[0] == "/framebuffer":
            with _lock:
                frame = _get_core().framebuffer()
            self._json(200, {"png_b64": _png_b64(frame), "w": 160, "h": 144})
        elif self.path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self._body()
            with _lock:
                core = _get_core()
                if path == "/load":
                    core.load(base64.b64decode(body["rom_b64"]))
                    self._json(200, {"ok": True, "fps": core.fps})
                elif path == "/reset":
                    core.reset()
                    self._json(200, {"ok": True})
                elif path == "/set_keys":
                    core.set_keys(int(body.get("mask", 0)))
                    self._json(200, {"ok": True})
                elif path == "/run_frame":
                    for _ in range(int(body.get("frames", 1))):
                        core.run_frame()
                    self._json(200, {"ok": True})
                elif path == "/run":
                    core.load(base64.b64decode(body["rom_b64"]))
                    core.reset()
                    schedule = {int(k): int(v) for k, v in body.get("keys", {}).items()}
                    mask = 0
                    for i in range(int(body["frames"])):
                        if i in schedule:
                            mask = schedule[i]
                        core.set_keys(mask)
                        core.run_frame()
                    self._json(200, {"png_b64": _png_b64(core.framebuffer())})
                else:
                    self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": repr(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    _get_core()  # warm up (load the core)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"oracle serving on http://{args.host}:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
