"""Agentic generation loop (leaner first cut).

Each iteration: ask the model for the complete `src/lib.rs`, build it OFFLINE in the Docker
sandbox (`--network none`), grade the artifact against the SameBoy oracle, and feed the
build/grade result back. The Cargo.toml is fixed by the harness (package `gb_emu`, cdylib,
no external crates) so the build is offline and the artifact contract is enforced; the model
only writes `src/lib.rs`.

A small local model is expected to score ~0 (often failing to even compile). Success here is
the loop itself running cleanly: generate -> build -> grade -> feedback, with a saved
artifact + meta.json.

    python harness/generate.py [model] [--iters N] [--until-build [--max-iters N]]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
sys.path.insert(0, str(ROOT / "harness"))

from providers import chat  # noqa: E402
from runner import WasmEmu  # noqa: E402
from grade import grade  # noqa: E402

IMAGE = "gameboy-eval-gen"
DEFAULT_MODEL = "qwen2.5-coder:7b"

CARGO_TOML = """[package]
name = "gb_emu"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[profile.release]
opt-level = "z"
"""

SYSTEM = f"""{(ROOT / 'env/TASK.md').read_text()}

--- spec/ABI.md ---
{(ROOT / 'spec/ABI.md').read_text()}

--- HOW TO RESPOND ---
The cargo project and Cargo.toml already exist and MUST NOT change (package `gb_emu`,
crate-type cdylib, NO external crates — std only). You implement ONLY `src/lib.rs`.
Reply with the COMPLETE contents of `src/lib.rs` in a single ```rust code block and nothing
else. Every export in spec/ABI.md must be present.
"""

RUST_BLOCK = re.compile(r"```(?:rust)?\s*\n(.*?)```", re.DOTALL)


def extract_rust(text: str) -> str | None:
    blocks = RUST_BLOCK.findall(text)
    return max(blocks, key=len).strip() if blocks else None


def build_offline(workdir: Path) -> tuple[bool, str]:
    """cargo build the candidate inside the sandbox with no network."""
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none",
         "-v", f"{workdir}:/task", IMAGE,
         "sh", "-c",
         "cargo build --release --lib --target wasm32-unknown-unknown 2>&1"],
        capture_output=True, text=True, timeout=600,
    )
    wasm = workdir / "target/wasm32-unknown-unknown/release/gb_emu.wasm"
    return (proc.returncode == 0 and wasm.exists()), proc.stdout + proc.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default=DEFAULT_MODEL)
    ap.add_argument("--iters", type=int, default=4,
                    help="iterations to run; with --until-build, counts only graded "
                         "(successful-build) rounds")
    ap.add_argument("--until-build", action="store_true",
                    help="don't let build failures consume --iters: keep retrying the build "
                         "(initially and on later regressions) until it compiles, bounded by "
                         "--max-iters")
    ap.add_argument("--max-iters", type=int, default=15,
                    help="hard cap on TOTAL attempts in --until-build mode (cost guard, since "
                         "every attempt is a paid model call)")
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="continuous-runtime budget (minutes); the task never 'finishes' "
                         "and overrides --iters")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = args.model.replace(":", "_").replace("/", "_")
    outdir = ROOT / "candidates" / f"{safe}__{ts}"
    workdir = outdir / "task"
    (workdir / "src").mkdir(parents=True, exist_ok=True)
    (workdir / "Cargo.toml").write_text(CARGO_TOML)

    messages = [{"role": "system", "content": SYSTEM}]
    feedback = "Begin. Send the complete src/lib.rs implementing the full ABI."
    history = []
    best_score, best_wasm = -1.0, None
    wasm_path = workdir / "target/wasm32-unknown-unknown/release/gb_emu.wasm"

    start = time.time()
    it = graded = 0  # graded = attempts that actually built (the rounds --until-build counts)
    while True:
        it += 1
        if args.minutes > 0:
            if (time.time() - start) / 60 >= args.minutes:
                break
            tag = f"iteration {it} (continuous {args.minutes:g}min)"
        elif args.until_build:
            if graded >= args.iters or it > args.max_iters:
                break
            tag = f"iteration {it} (built {graded}/{args.iters}, cap {args.max_iters})"
        else:
            if it > args.iters:
                break
            tag = f"iteration {it}/{args.iters}"
        print(f"\n===== {tag} ({args.model}) =====")
        # Keep context bounded (system + recent turns) so calls stay fast and don't time out.
        if len(messages) > 7:
            messages = [messages[0]] + messages[-6:]
        messages.append({"role": "user", "content": feedback})
        t0 = time.time()
        try:
            reply = chat(messages, args.model, timeout=300)
        except Exception as e:  # noqa: BLE001
            print(f"model call failed: {e!r}")
            if args.minutes > 0 or args.until_build:  # resilient modes: keep going (capped)
                feedback = "(previous call failed; keep improving) " + feedback
                continue
            break
        messages.append({"role": "assistant", "content": reply})
        print(f"  model replied in {time.time()-t0:.0f}s ({len(reply)} chars)")

        code = extract_rust(reply)
        if not code:
            feedback = "No ```rust block found. Reply ONLY with the full src/lib.rs in a ```rust block."
            history.append({"iter": it, "build_ok": False, "note": "no code block"})
            continue
        (workdir / "src/lib.rs").write_text(code)

        ok, log = build_offline(workdir)
        rec = {"iter": it, "build_ok": ok}
        if not ok:
            print("  build FAILED")
            feedback = ("Build failed:\n" + log[-2500:] +
                        "\nReturn the complete corrected src/lib.rs in a ```rust block.")
            history.append(rec)
            continue

        graded += 1  # compiled — counts as one round toward --iters (in --until-build mode)
        print("  build OK -> grading")
        try:
            report = grade(lambda: WasmEmu(str(wasm_path)), args.model)
            score = report["overall"]
            rec["score"] = score
            print(f"  score = {score:.4f} [{report['band']}]")
            if score > best_score:
                best_score = score
                best_wasm = outdir / "gb_emu.wasm"
                best_wasm.write_bytes(wasm_path.read_bytes())
                (outdir / "scores.json").write_text(json.dumps(report, indent=2))
            feedback = (f"Build OK. Composite={score:.3f} "
                        f"(replay={report['sections']['replay']:.2f}, "
                        f"procedural={report['sections']['procedural']:.2f}). "
                        "Improve accuracy; return the full src/lib.rs again.")
        except Exception as e:  # noqa: BLE001
            print(f"  grading raised (wasm likely trapped): {e!r}")
            rec["score"] = 0.0
            feedback = (f"It built but crashed when run: {e!r}\n"
                        "Fix the runtime behavior and return the full src/lib.rs.")
        history.append(rec)

    meta = {
        "model": args.model,
        "created": ts,
        "iterations": history,
        "best_score": best_score if best_score >= 0 else None,
        "artifact": "gb_emu.wasm" if best_wasm else None,
    }
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\nsaved {outdir}")
    print(f"best score: {meta['best_score']}")


if __name__ == "__main__":
    main()
