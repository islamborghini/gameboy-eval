# gameboy-eval

*An open, free, local-first benchmark that measures how well coding agents can build a **Game Boy (DMG)** emulator from scratch — graded automatically, deterministically, and for free on a laptop.*

This is a faithful, open take on the *idea* behind Mechanize's GBA Eval, retargeted to the original Game Boy. A coding agent is dropped into a sandboxed, **offline** container with a black-box reference emulator (an **oracle**) and told to write an emulator. We save the artifact (a Rust → `wasm32-unknown-unknown` module) and grade it later, offline, with the model out of the loop — so grading is free, fast, reproducible, and provider-independent.

## How grading works (composite, replay-led)

```
overall = 0.60 · replay  +  0.20 · audio  +  0.20 · procedural
```

- **replay** — run the candidate and the SameBoy **oracle** in lockstep on recorded inputs and score how *visually close* each frame stays (block-SSIM; "almost the same almost everywhere", never exact-match). The centerpiece.
- **procedural** — open self-checking GB test ROMs (`c-sp/game-boy-test-roms`) scored on final state (`LD B,B` Fibonacci registers, or screenshot-match for image tests).
- **audio** — log-mel spectrogram distance through the same per-frame pipeline.

Score bands (apply to the **composite**): doesn't-run ~0–5% · barely-works ~15–30% · plays-incorrectly ~45–55% · mostly-playable ~70% · near-reference ~85–99% · reference-vs-itself = 1.00.

## The artifact contract

A candidate is a Rust cargo project (package `gb_emu`) that builds with **exactly**:

```
cargo build --release --lib --target wasm32-unknown-unknown
```

to the fixed path `target/wasm32-unknown-unknown/release/gb_emu.wasm`, exporting the lockstep ABI in [`spec/ABI.md`](spec/ABI.md) (`set_keys` / `run_frame` / `framebuffer` / `audio` + `init`/`reset`/`load_rom`). Grading drives this ABI in WASM via `wasmtime`. No `.cargo/config.toml`, no custom `RUSTFLAGS`.

## Status / build order

- [x] **M0** Scaffold + repo layout + Python 3.12 venv + NOTICE
- [x] **M1** Toolchain: Rust + `wasm32-unknown-unknown` + wasmtime + Docker; hello-world cdylib → `.wasm` → callable via wasmtime
- [x] **M2** SameBoy driven as a black-box **oracle** via its libretro core (dmg-acid2 renders, deterministic, DMG-forced)
- [x] **M3** Lockstep harness + reference candidate — (a) SSIM metric validated *oracle-vs-perturbed*; (b) rboy → `.wasm` scores **1.0000** vs the oracle
- [x] **M4** Full grader: replay SSIM + procedural ROMs + audio + composite + score-band report (oracle 0.9988, rboy 0.7333, broken 0.0)
- [x] **M5** Agentic generation (leaner cut): harness drives Ollama → writes `src/lib.rs` → builds OFFLINE in a `--network none` sandbox → grades vs oracle → feeds back → saves artifact (qwen2.5-coder:7b & qwen3:8b ran end-to-end, scored ~0 as expected)
- [x] **M6** Static [`leaderboard/`](leaderboard/) — ranked composite + score bands, and the candidate `gb_emu.wasm` runs **in-browser** on a canvas (validated via node: zero imports, renders dmg-acid2)
- [x] **Hardening** Oracle in its own Linux container reachable only over an *internal* Docker network — the offline sandbox reaches the oracle but **not** the internet ([`scripts/run-sandbox.sh`](scripts/run-sandbox.sh)); `generate.py --minutes` continuous-runtime mode
- [ ] **M6** Audio polish + leaderboard with in-browser WASM artifacts

The spine deliberately **validates the grading harness against a known-good emulator (M2–M4) before building the generation side (M5)** — "grader against itself", at the full-emulator level.

See [`spec/ABI.md`](spec/ABI.md) for the candidate ABI contract.

## Prerequisites (macOS, Apple Silicon)

```sh
# Rust + WASM target
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y -t wasm32-unknown-unknown
# WASM runtime + Game Boy assembler (needed to build SameBoy's open boot ROM)
brew install wasmtime rgbds
# Python 3.12 venv for the SSIM/audio stack
python3.12 -m venv .venv && .venv/bin/pip install numpy scipy pillow requests wasmtime
# Docker Desktop must be running (the offline generation sandbox)
```

## Quick start

```sh
python scripts/fetch_data.py            # vendor the c-sp test-ROM suite -> data/test-roms/
docker build -t gameboy-eval-gen env/   # offline build sandbox

# grade a candidate (composite + score band + scores.json)
.venv/bin/python grader/grade.py reference/known-good/target/wasm32-unknown-unknown/release/gb_emu.wasm
# -> rboy known-good scores ~0.80 (passes Blargg cpu_instrs/instr_timing/mem_timing)

# agentic generation with a local model (expect ~0 for a small model)
.venv/bin/python harness/generate.py qwen2.5-coder:7b --iters 4
```

## Control panel (GUI)

Prefer a browser to the terminal? A tiny **stdlib-only** server wraps the same scripts — no
extra dependencies, localhost-only:

```sh
.venv/bin/python webapp/server.py        # -> http://127.0.0.1:8000
```

Menu: **Dashboard** (prerequisite checks) · **Generate** · **Grade** · **Candidates** ·
**Compare** (play a model's emulator next to the SameBoy oracle on the same ROM, side by
side) · **Leaderboard** · **Provider** (set an OpenRouter / OpenAI-compatible key for the
session, held in memory only). It shells out to the CLIs above and streams their output live.

## Layout

```
gameboy-eval/
├── spec/ABI.md            # the lockstep WASM ABI candidates must export
├── env/                   # offline generation container + TASK.md
├── oracle/                # SameBoy wrapped as a black-box HTTP service + client
├── harness/               # generation (agentic) + provider layer
├── grader/                # replay-SSIM / procedural / audio / composite / report
├── webapp/                # localhost control panel — a GUI over the CLIs (stdlib http.server)
├── reference/             # known-good emulator(s) to validate the grader
├── data/sm83/             # (optional) CPU vectors for internal smoke-tests
├── replays/               # short HOMEBREW input recordings
└── candidates/<model>__<ts>/{meta.json, src/, gb_emu.wasm}
```

## Licensing

Upstream assets are vendored under their own open licenses with attribution in [`NOTICE`](NOTICE). The Nintendo boot ROM is **never** shipped — we use SameBoy's open boot ROM for both oracle and candidate. Replay ROMs are **homebrew only**.
