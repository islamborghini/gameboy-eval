# gameboy-eval

> An open, free, local-first benchmark that measures how well a coding agent can build a **Game Boy (DMG) emulator** from scratch. Grading is automatic, deterministic, and runs for free on a laptop.

## 1. What is gameboy-eval

gameboy-eval gives a coding agent one job: write a working Game Boy emulator in Rust, with no libraries, starting from nothing. We drop the agent into a sandboxed, offline container alongside a black-box reference emulator (the "oracle"), let it iterate, and save whatever it produces as a portable WebAssembly module. Later, with the model completely out of the loop, we grade that module by running it next to the oracle and measuring how closely it matches.

The whole thing rests on one idea: you do not need to hand-write a test suite to know whether an emulator is correct, because you already have a correct emulator. So you grade a candidate by **differential comparison against a trusted reference**, frame by frame. That keeps grading cheap, reproducible, and independent of whichever model or provider produced the code.

It is an open, Game Boy take on the idea behind Mechanize's GBA Eval.

## 2. Motivation

_Author to write._

## 3. How we grade LLMs

Grading never asks the model anything. It runs the saved artifact and scores it against the oracle on three axes, then folds them into a single composite:

```
overall = 0.60 * replay  +  0.20 * audio  +  0.20 * procedural
```

**Replay (the centerpiece).** We run the candidate and the SameBoy oracle in lockstep on the same recorded inputs and compare every rendered frame. The comparison uses structural similarity (block SSIM) instead of exact pixel equality, because two correct emulators are almost never bit-identical. The target is "almost the same almost everywhere," which tracks human-perceived correctness far better than an exact match.

**Procedural.** We run a set of open, self-checking Game Boy test ROMs and compare the final screen to the oracle's. These ROMs are written to exercise tricky CPU, timing, and PPU behavior, so passing them is strong evidence that the core is accurate.

**Audio.** We compare the candidate's sound output to the oracle's using a log-mel spectrogram distance, through the same per-frame pipeline.

Results land in human-readable bands, so a single number is easy to interpret:

| band | composite |
|---|---|
| doesn't run | ~0 to 5% |
| barely works | ~15 to 30% |
| plays incorrectly | ~45 to 55% |
| mostly playable | ~70% |
| near-reference | ~85 to 99% |
| reference vs itself | 100% |

Two design choices make this practical:

- **The artifact is a portable wasm module behind a fixed ABI.** A candidate is a Rust crate (package `gb_emu`) that must build with exactly `cargo build --release --lib --target wasm32-unknown-unknown` and export a small lockstep interface (`init`, `load_rom`, `reset`, `set_keys`, `run_frame`, `framebuffer`, `audio`). The grader drives that interface from Python through `wasmtime`. The full contract lives in [`spec/ABI.md`](spec/ABI.md).
- **The model is out of the loop at grading time.** Generation happens once and costs money. Grading happens any number of times, offline, for free, and returns the same answer on every run.

## 4. Why Game Boy

The original Game Boy (DMG) hits a sweet spot for a benchmark like this:

- **Small enough to be tractable, rich enough to be hard.** An 8-bit CPU (Sharp SM83), a simple but quirky PPU, timers, and audio. A faithful emulator is a real engineering effort rather than a weekend toy, yet it still fits in a single file.
- **A culture of precise, open test ROMs.** Decades of emulator-accuracy work left behind well-known, self-checking ROMs that pin down exact hardware behavior, which is exactly what a grader needs.
- **Everything we depend on is open.** No proprietary BIOS is required, and the reference emulator, the test ROMs, and the tooling are all freely available.

The main pieces we build on:

- [**SameBoy**](https://github.com/LIJI32/SameBoy), a highly accurate open-source Game Boy emulator. We run it as the black-box oracle (through its libretro core) and use its open boot ROM.
- [**c-sp/game-boy-test-roms**](https://github.com/c-sp/game-boy-test-roms), a curated bundle of the community's accuracy test ROMs, used for the procedural section.
- [**dmg-acid2**](https://github.com/mattcurrie/dmg-acid2) by Matt Currie, a single-frame PPU correctness test (the smiley face you may have seen).
- [**rboy**](https://github.com/mvdnes/rboy), a known-good third-party emulator we compile to wasm to confirm the grader itself is sound.
- [**Pan Docs**](https://gbdev.io/pandocs/), the canonical Game Boy hardware reference, and [**RGBDS**](https://rgbds.gbdev.io/) for assembling the open boot ROM.

## 5. Quickstart

Prerequisites (tested on macOS, Apple Silicon):

```sh
# Rust plus the wasm target
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y -t wasm32-unknown-unknown
# wasm runtime and the Game Boy assembler (for SameBoy's open boot ROM)
brew install wasmtime rgbds
# Python 3.12 environment for the scoring stack
python3.12 -m venv .venv && .venv/bin/pip install numpy scipy pillow requests wasmtime
# Docker Desktop must be running (it hosts the offline generation sandbox)
```

Then:

```sh
python scripts/fetch_data.py            # vendor the c-sp test ROMs into data/test-roms/
docker build -t gameboy-eval-gen env/   # build the offline generation sandbox

# grade a candidate (prints the composite and band, writes scores.json)
.venv/bin/python grader/grade.py reference/known-good/target/wasm32-unknown-unknown/release/gb_emu.wasm

# generate with a model (small local models are expected to score ~0)
.venv/bin/python harness/generate.py qwen2.5-coder:7b --iters 4
```

By default the harness talks to a local Ollama server. To use a hosted model, set `OPENROUTER_API_KEY` for OpenRouter, or `OPENAI_BASE_URL` plus `OPENAI_API_KEY` for any OpenAI-compatible endpoint. The provider layer lives in [`harness/providers.py`](harness/providers.py).

## 6. GUI

If you would rather not touch the command line, a small browser control panel wraps the same scripts. It uses only the Python standard library and binds to localhost.

```sh
.venv/bin/python webapp/server.py        # then open http://127.0.0.1:8000
```

What it gives you:

- **Dashboard:** prerequisite checks (Docker, the build image, fetched ROMs) at a glance.
- **Generate:** run the agentic loop against your chosen provider, with a "keep retrying until it builds" mode so build failures do not eat the iteration budget.
- **Grade** and **Candidates:** grade an artifact and browse past runs with live status.
- **Oracle:** watch a candidate next to the real SameBoy oracle on the graded test ROMs.
- **Play:** run any candidate's emulator in your browser with live keyboard input and audio, with the reference emulator side by side. Bring your own homebrew ROM.
- **Leaderboard:** ranked results with a per-section score chart.
- **Provider:** pick and save your model provider (Ollama, OpenRouter, or OpenAI-compatible). Settings persist across restarts.

## 7. Layout

```
gameboy-eval/
├── spec/ABI.md            # the lockstep wasm ABI every candidate must export
├── env/                   # offline generation container + TASK.md
├── oracle/                # SameBoy wrapped as a black-box HTTP service + client
├── harness/               # the agentic generation loop and the provider layer
├── grader/                # replay SSIM, procedural, audio, composite, report
├── webapp/                # localhost control panel (a GUI over the CLIs)
├── reference/             # known-good emulators used to validate the grader
├── leaderboard/           # static ranked results and an in-browser wasm player
├── data/                  # fetched test ROMs (not committed)
└── candidates/<model>__<ts>/   # saved artifact, source, and scores per run
```

## 8. Licensing

The project itself is MIT licensed. Upstream assets are vendored under their own open licenses, with attribution in [`NOTICE`](NOTICE). The proprietary Nintendo boot ROM is never shipped: both the oracle and the candidates use SameBoy's open boot ROM. Replay ROMs are homebrew only.

## 9. Contributing

Contributions are welcome. A few good places to start:

- **New reference candidates** that further validate the grader.
- **Grader improvements**, especially the audio pipeline.
- **More replay and procedural scenarios** (homebrew or open test ROMs only, never copyrighted games).
- **Provider integrations** in [`harness/providers.py`](harness/providers.py).

Two project rules to keep in mind: the grading harness stays deterministic and model-independent, and no copyrighted ROMs or BIOS files ever enter the repository. For anything larger, open an issue to discuss it before sending a pull request.
