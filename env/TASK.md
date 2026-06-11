# TASK — Implement a Game Boy (DMG) emulator from scratch

You are a senior systems engineer. Your task is to implement an accurate emulator of the
original Game Boy (model **DMG**) in Rust, compiled to WebAssembly.

This is a **long-horizon** task. There is no deadline and no reward for finishing quickly.
Work carefully and incrementally; prefer correctness over coverage. The task does not end —
keep improving accuracy for as long as you are running. If you believe you are "done",
pick the next most-impactful inaccuracy and fix it.

## What you must produce

A Rust cargo project rooted at `/task/` whose library crate is named `gb_emu` and builds,
with **exactly**:

    cargo build --release --lib --target wasm32-unknown-unknown

to `target/wasm32-unknown-unknown/release/gb_emu.wasm`, exporting the ABI specified in
`/task/spec/ABI.md`. Do **not** add a `.cargo/config.toml`, custom `RUSTFLAGS`, or anything
that changes the build command or the artifact path. The ABI is the only fixed contract;
every internal design decision (CPU, PPU, timing, memory mapping, MBCs, APU) is yours.

## What you are given (read-only)

- `/task/spec/ABI.md` — the exact WASM exports your module must provide.
- `/task/spec/pandocs.html` — Pan Docs, the community Game Boy hardware reference.
- `/task/spec/boot_rom.bin` — an open-source DMG boot ROM. Load it via `load_boot_rom`
  so that your power-on behavior matches the reference.
- `/task/dev-roms/` — a handful of **homebrew** Game Boy ROMs you may use to self-test.
  (These are for your own debugging; the grading ROMs and input recordings are different
  and are held out from you.)

## Tools available to you

- A normal shell, `rustc`/`cargo` with the `wasm32-unknown-unknown` target, and `wasmtime`.
- `oracle` — a command-line client to a **reference Game Boy emulator** running as a remote
  black box. You may run any ROM through it and observe its output (framebuffers, audio),
  but you cannot see its source. Use it as ground truth:
    - batch:   `oracle run <rom> <frames> [--keys <replay.txt>] [--dump-frames <dir>] [--dump-audio <wav>]`
    - session: `oracle session ...` exposing `set-keys` / `run-frame` / `framebuffer` /
      `audio`, shaped exactly like your own ABI, so you can diff your emulator against the
      reference one frame at a time and localize exactly where you diverge.

You have **no internet access**. Everything you need is on disk or behind `oracle`.

## How you will be graded (so you know what "good" means)

Offline, after you stop, your `gb_emu.wasm` is driven in lockstep against the reference and
scored on a composite in [0,1]:

    overall = 0.60 · replay  +  0.20 · audio  +  0.20 · procedural

- **replay** (largest weight) — short recorded input sequences are played into both your
  emulator and the reference; each frame is compared with a structural-similarity metric
  that rewards "looks almost the same" rather than exact pixel equality. This measures
  whether real games actually play correctly.
- **procedural** — standard self-checking Game Boy test ROMs, scored on their final state.
- **audio** — your audio output is compared to the reference in the spectral domain.

A perfect reference-vs-itself run scores 1.00. You will not be told the grading ROMs or
recordings; do not special-case anything.

## Suggested order of attack (not a constraint)

A working SM83 CPU first, then the memory bus and timers (DIV/TIMA), then the PPU
(background, window, sprites, the STAT/LY timing) so something renders, then joypad input,
then MBC1/MBC3 so larger ROMs load, then the APU for audio. Use `oracle` constantly to
localize divergences frame by frame.
