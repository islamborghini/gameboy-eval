"""Tiny local control panel for gameboy-eval — drive the CLI tools from a browser.

    .venv/bin/python webapp/server.py [port]        # default http://127.0.0.1:8000

Stdlib only (http.server + background subprocess threads); binds to localhost. It shells out
to the very same scripts the README documents — generate / grade / build_leaderboard /
fetch_data — and streams their stdout back to the page. Long jobs run in worker threads; the
page polls /api/log. Provider settings (e.g. an OpenRouter key) are held in memory and
overlaid onto spawned jobs only — never written to disk.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
PY = sys.executable  # the interpreter running us — launch via .venv/bin/python to inherit deps

# Provider config: persisted to disk (gitignored — holds API keys) and reloaded on restart.
# PROVIDER_CFG is the saved settings; PROVIDER_ENV is what we overlay onto spawned jobs.
PROVIDER_FILE = WEB / "provider.json"
PROVIDER_CFG: dict[str, str] = {}
PROVIDER_ENV: dict[str, str] = {}
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

JOBS: dict[str, "Job"] = {}
LOCK = threading.Lock()

CTYPES = {".html": "text/html", ".js": "application/javascript", ".json": "application/json",
          ".css": "text/css", ".wasm": "application/wasm", ".gb": "application/octet-stream",
          ".bin": "application/octet-stream"}

# The compare viewer runs a real emulator server-side (oracle or candidate) and ships PNG
# frames to the browser. Heavy + uses the ctypes SameBoy core, so serialize clip builds.
CLIP_LOCK = threading.Lock()
MAX_CLIP_FRAMES = 600

# ROMs offered in the compare viewer — first existing path per key wins (homebrew/open only).
ROMS = {
    "dmg-acid2": ("dmg-acid2 — PPU visual test (static)", [
        ROOT / "data/test-roms/dmg-acid2/dmg-acid2.gb",
        ROOT / "leaderboard/demo/dmg-acid2.gb",
        ROOT / "oracle/SameBoy/.github/actions/dmg-acid2.gb"]),
    "cpu_instrs": ("blargg cpu_instrs — scrolling text (moving)", [
        ROOT / "data/test-roms/blargg/cpu_instrs/cpu_instrs.gb"]),
    "instr_timing": ("blargg instr_timing", [
        ROOT / "data/test-roms/blargg/instr_timing/instr_timing.gb"]),
}


# --------------------------------------------------------------------------- jobs

class Job:
    """A spawned CLI command whose combined stdout/stderr is buffered for the page to poll."""

    def __init__(self, title: str, argv: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.argv = argv
        self.lines: list[str] = []
        self.status = "running"            # running | done | failed
        self.returncode: int | None = None
        self.proc: subprocess.Popen | None = None

    def run(self) -> None:
        env = {**os.environ, **PROVIDER_ENV}
        self.lines.append("$ " + " ".join(self.argv))
        try:
            # start_new_session detaches the job into its own process group, so a Ctrl-C that
            # restarts this server doesn't also kill a long-running generation.
            self.proc = subprocess.Popen(
                self.argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
            )
        except Exception as e:  # noqa: BLE001
            self.lines.append(f"failed to start: {e!r}")
            self.status = "failed"
            return
        for line in self.proc.stdout:      # type: ignore[union-attr]
            self.lines.append(line.rstrip("\n"))
        self.returncode = self.proc.wait()
        self.status = "done" if self.returncode == 0 else "failed"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def start_job(title: str, argv: list[str]) -> str:
    job = Job(title, argv)
    with LOCK:
        JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return job.id


def build_argv(action: str, p: dict) -> tuple[str, list[str]]:
    """Map a GUI action + params onto the CLI argv the README would run."""
    if action == "generate":
        model = (p.get("model") or "").strip()
        if not model:
            raise ValueError("a model id is required")
        argv = [PY, "harness/generate.py", model]
        minutes = float(p.get("minutes") or 0)
        if minutes > 0:
            argv += ["--minutes", str(minutes)]
        else:
            argv += ["--iters", str(int(p.get("iters") or 4))]
            if p.get("until_build"):
                argv += ["--until-build", "--max-iters", str(int(p.get("max_iters") or 15))]
        return f"generate · {model}", argv
    if action == "grade":
        target = (p.get("target") or "").strip()
        if target == "oracle":
            return "grade · oracle self-play", [PY, "grader/grade.py", "oracle"]
        wasm = ROOT / "candidates" / target / "gb_emu.wasm"
        if not (ROOT / "candidates" / target).is_dir() or not wasm.exists():
            raise ValueError("unknown candidate")
        out = ROOT / "leaderboard/results" / f"{target}.json"   # feeds build_leaderboard.py
        return f"grade · {target}", [PY, "grader/grade.py", str(wasm), str(out)]
    if action == "leaderboard":
        return "build leaderboard", [PY, "scripts/build_leaderboard.py"]
    if action == "fetch":
        return "fetch test ROMs", [PY, "scripts/fetch_data.py"]
    raise ValueError(f"unknown action: {action}")


# --------------------------------------------------------------------------- status

def apply_provider_env() -> None:
    """Make the saved provider authoritative for spawned jobs by overlaying its vars and
    blanking the others, so the precedence in providers.py resolves to the chosen one."""
    PROVIDER_ENV.clear()
    if not PROVIDER_CFG.get("provider"):
        return  # nothing saved -> let jobs inherit the shell env (back-compat)
    p = PROVIDER_CFG["provider"]
    PROVIDER_ENV.update({"OPENROUTER_API_KEY": "", "OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""})
    if p == "openrouter":
        PROVIDER_ENV["OPENROUTER_API_KEY"] = PROVIDER_CFG.get("openrouter_key", "")
    elif p == "openai":
        PROVIDER_ENV["OPENAI_BASE_URL"] = PROVIDER_CFG.get("openai_base_url", "")
        PROVIDER_ENV["OPENAI_API_KEY"] = PROVIDER_CFG.get("openai_key", "")
    if PROVIDER_CFG.get("ollama_url"):
        PROVIDER_ENV["OLLAMA_URL"] = PROVIDER_CFG["ollama_url"]


def load_provider_cfg() -> None:
    global PROVIDER_CFG
    try:
        PROVIDER_CFG = json.loads(PROVIDER_FILE.read_text()) if PROVIDER_FILE.exists() else {}
    except Exception:  # noqa: BLE001
        PROVIDER_CFG = {}
    apply_provider_env()


def save_provider_cfg() -> None:
    try:
        PROVIDER_FILE.write_text(json.dumps(PROVIDER_CFG, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"could not persist provider config: {e!r}")


def provider_status() -> dict:
    if PROVIDER_CFG.get("provider"):                # an explicit saved choice wins
        c = PROVIDER_CFG
        return {
            "active": c["provider"], "saved": True,
            "openrouter_key_set": bool(c.get("openrouter_key")),
            "openai_base_url": c.get("openai_base_url", ""),
            "openai_key_set": bool(c.get("openai_key")),
            "ollama_url": c.get("ollama_url", "") or DEFAULT_OLLAMA,
        }
    env = {**os.environ, **PROVIDER_ENV}            # else infer from the environment
    active = ("openrouter" if env.get("OPENROUTER_API_KEY")
              else "openai" if env.get("OPENAI_BASE_URL") else "ollama")
    return {
        "active": active, "saved": False,
        "openrouter_key_set": bool(env.get("OPENROUTER_API_KEY")),
        "openai_base_url": env.get("OPENAI_BASE_URL") or "",
        "openai_key_set": bool(env.get("OPENAI_API_KEY")),
        "ollama_url": env.get("OLLAMA_URL") or DEFAULT_OLLAMA,
    }


# `docker info` is slow (seconds) on macOS, so never block a request on it: refresh in the
# background every ~20s and always answer instantly from the last result.
_DOCKER_CACHE = {"t": 0.0, "val": (False, False), "busy": False}


def _refresh_docker() -> None:
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode != 0:
            val = (False, False)
        else:
            img = subprocess.run(["docker", "images", "-q", "gameboy-eval-gen"],
                                 capture_output=True, text=True, timeout=8)
            val = (True, bool(img.stdout.strip()))
    except Exception:  # noqa: BLE001
        val = (False, False)
    _DOCKER_CACHE.update(t=time.time(), val=val, busy=False)


def docker_state() -> tuple[bool, bool]:
    """(docker running?, gameboy-eval-gen image built?), cached + refreshed off the hot path."""
    if not _DOCKER_CACHE["busy"] and time.time() - _DOCKER_CACHE["t"] >= 20:
        _DOCKER_CACHE["busy"] = True
        threading.Thread(target=_refresh_docker, daemon=True).start()
    return _DOCKER_CACHE["val"]


def status() -> dict:
    docker, gen_image = docker_state()
    cands = [d for d in (ROOT / "candidates").glob("*") if d.is_dir()]
    return {
        "provider": provider_status(),
        "python": PY,
        "root": str(ROOT),
        "docker": docker,
        "gen_image": gen_image,
        "data_present": (ROOT / "data/test-roms").is_dir(),
        "candidates": len(cands),
    }


def _safe_model(model: str) -> str:
    return model.replace(":", "_").replace("/", "_")  # matches generate.py's outdir naming


def running_generations() -> dict[str, int]:
    """safe-model name -> count of live `harness/generate.py` processes for it."""
    try:
        out = subprocess.run(["ps", "-Ao", "command"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return {}
    counts: dict[str, int] = {}
    for line in out.splitlines():
        if "harness/generate.py" not in line:
            continue
        toks = line.split()
        for i, t in enumerate(toks):
            if t.endswith("generate.py") and i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                safe = _safe_model(toks[i + 1])
                counts[safe] = counts.get(safe, 0) + 1
                break
    return counts


def candidates() -> list[dict]:
    running = running_generations()
    out = []
    for d in sorted((ROOT / "candidates").glob("*"), reverse=True):
        if not d.is_dir():
            continue
        info = {"name": d.name, "model": None, "best_score": None, "created": None,
                "artifact": (d / "gb_emu.wasm").exists(), "status": "done"}
        meta = d / "meta.json"
        if meta.exists():                       # generate.py writes meta.json only at the end
            m = json.loads(meta.read_text())
            info.update(model=m.get("model"), best_score=m.get("best_score"),
                        created=m.get("created"))
        elif running.get(d.name.rsplit("__", 1)[0], 0) > 0:
            info["status"] = "running"          # newest no-meta dir of a live model claims it
            running[d.name.rsplit("__", 1)[0]] -= 1
        else:
            info["status"] = "stopped"          # killed/crashed, or an older same-model leftover
        out.append(info)
    return out


def leaderboard() -> dict | None:
    f = ROOT / "leaderboard/leaderboard.json"
    return json.loads(f.read_text()) if f.exists() else None


# --------------------------------------------------------------------------- compare viewer

def resolve_rom(key: str) -> Path | None:
    for p in ROMS.get(key, ("", []))[1]:
        if p.exists():
            return p
    return None


def available_roms() -> list[dict]:
    return [{"key": k, "label": lab}
            for k, (lab, paths) in ROMS.items() if any(p.exists() for p in paths)]


def _emu_path():
    for sub in ("oracle", "grader"):
        p = str(ROOT / sub)
        if p not in sys.path:
            sys.path.insert(0, p)


def build_clip(target: str, rom_key: str, frames: int) -> dict:
    """Run the oracle or a candidate for N frames and return them as base64 PNGs.

    `target` is "oracle" (SameBoy via libretro) or a candidate dir (its gb_emu.wasm via
    wasmtime) — the same driver classes the grader uses. Captures partial frames and a clear
    error string if a candidate traps, so a broken model is still watchable.
    """
    frames = max(1, min(frames, MAX_CLIP_FRAMES))
    rom_path = resolve_rom(rom_key)
    if not rom_path:
        raise ValueError("unknown or unavailable ROM")
    if target != "oracle" and not (ROOT / "candidates" / target / "gb_emu.wasm").exists():
        raise ValueError("unknown candidate")

    _emu_path()
    import base64
    import io

    from PIL import Image

    rom = rom_path.read_bytes()
    out: list[str] = []
    err = None
    with CLIP_LOCK:
        try:
            if target == "oracle":
                from sameboy import OracleEmu
                emu = OracleEmu()
            else:
                from runner import WasmEmu
                emu = WasmEmu(str(ROOT / "candidates" / target / "gb_emu.wasm"))
            emu.load(rom, None)
            emu.reset()
            for _ in range(frames):
                emu.set_keys(0)
                emu.run_frame()
                buf = io.BytesIO()
                Image.fromarray(emu.framebuffer(), "RGBA").save(buf, "PNG")
                out.append(base64.b64encode(buf.getvalue()).decode())
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    return {"frames": out, "count": len(out), "w": 160, "h": 144, "error": err}


# --------------------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet: the page polls /api/log once a second
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path):
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CTYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, root: Path, rel: str):
        """Serve rel under root with a path-traversal guard."""
        target = (root / rel).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            self.send_error(403)
            return
        self._file(target)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path in ("/", "/index.html"):
            return self._file(WEB / "index.html")
        if path == "/app.js":
            return self._file(WEB / "app.js")
        if path.startswith("/leaderboard/"):       # the existing static site + its assets
            return self._static(ROOT / "leaderboard", path[len("/leaderboard/"):])
        if path.startswith("/candidate/"):          # serve a candidate's gb_emu.wasm to the Play page
            return self._static(ROOT / "candidates", path[len("/candidate/"):])
        if path == "/api/status":
            return self._json(status())
        if path == "/api/candidates":
            return self._json(candidates())
        if path == "/api/leaderboard":
            return self._json(leaderboard())
        if path == "/api/provider":                 # cheap: provider settings only (no docker)
            return self._json(provider_status())
        if path == "/api/roms":
            return self._json(available_roms())
        if path == "/api/clip":
            target = (q.get("target") or ["oracle"])[0]
            rom = (q.get("rom") or [""])[0]
            fr = int((q.get("frames") or ["180"])[0])
            try:
                return self._json(build_clip(target, rom, fr))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/log":
            jid = (q.get("id") or [""])[0]
            off = int((q.get("offset") or ["0"])[0])
            job = JOBS.get(jid)
            if not job:
                return self._json({"error": "no such job"}, 404)
            new = job.lines[off:]
            return self._json({"lines": new, "offset": off + len(new),
                               "status": job.status, "returncode": job.returncode})
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/run":
            try:
                title, argv = build_argv(body.get("action", ""), body)
            except (ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"id": start_job(title, argv), "title": title})
        if path == "/api/stop":
            job = JOBS.get(body.get("id", ""))
            if job:
                job.stop()
            return self._json({"ok": bool(job)})
        if path == "/api/provider":
            if body.get("clear"):                       # delete all saved provider settings
                PROVIDER_CFG.clear()
                PROVIDER_FILE.unlink(missing_ok=True)
                apply_provider_env()
                return self._json(provider_status())
            PROVIDER_CFG["provider"] = (body.get("provider") or "ollama").strip()
            secret = {"openrouter_key", "openai_key"}
            for f in ("openrouter_key", "openai_base_url", "openai_key", "ollama_url"):
                if f not in body:
                    continue                            # field not shown for this provider — keep
                v = (body.get(f) or "").strip()
                if v:
                    PROVIDER_CFG[f] = v                 # edited
                elif f not in secret:
                    PROVIDER_CFG.pop(f, None)           # blank url = cleared
                # blank secret = keep the saved key (it is never echoed back to the form)
            save_provider_cfg()
            apply_provider_env()
            return self._json(provider_status())
        self.send_error(404)


class QuietServer(ThreadingHTTPServer):
    """A browser that hangs up mid-response (polling/navigating) raises BrokenPipeError /
    ConnectionResetError — benign; swallow those instead of dumping a traceback."""

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def main():
    load_provider_cfg()                     # restore persisted provider settings
    docker_state()                          # kick off the background docker probe so it's warm
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = None
    for port in range(want, want + 10):       # skip past an already-bound port
        try:
            srv = QuietServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            print(f"port {port} in use, trying {port + 1}…")
    if srv is None:
        sys.exit(f"no free port in {want}–{want + 9}; pass one: webapp/server.py <port>")
    print(f"gameboy-eval control panel → http://127.0.0.1:{port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
