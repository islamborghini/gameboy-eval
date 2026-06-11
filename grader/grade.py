"""End-to-end grader: drive a candidate against the oracle and emit a composite score.

    python grader/grade.py <path/to/gb_emu.wasm> [scores.json]
    python grader/grade.py oracle            # oracle self-play (sanity: ~1.0)

Sections:
  replay     candidate vs oracle, replay-SSIM on the settled tail (boot-offset safe)
  procedural screenshot-vs-oracle pass rate over a small test-ROM suite
  audio      log-mel spectrogram distance (0 if the candidate emits no audio)
  overall    0.60*replay + 0.20*audio + 0.20*procedural
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))

from sameboy import OracleEmu  # noqa: E402
from runner import WasmEmu  # noqa: E402
from replay import drive, score_replay_aligned  # noqa: E402
from audio import capture_audio, score_audio  # noqa: E402
from procedural_roms import (  # noqa: E402
    score_procedural, final_frame, DEFAULT_FRAMES as PROC_FRAMES,
)
from report import build_report, print_summary, write_scores  # noqa: E402

import hashlib  # noqa: E402

# The oracle is deterministic, so its output for (rom, frames, schedule) is cached and
# reused across candidates (big win for batch grading / repeated validation runs).
_oracle_cache: dict = {}


def _ocache(kind, rom, frames, schedule, compute):
    key = (kind, hashlib.md5(rom).hexdigest(), frames, tuple(sorted(schedule.items())))
    if key not in _oracle_cache:
        _oracle_cache[key] = compute()
    return _oracle_cache[key]

ACTIONS = ROOT / "oracle/SameBoy/.github/actions"
TR = ROOT / "data/test-roms"  # the fetched c-sp suite (scripts/fetch_data.py)


def _exists(paths):
    return [p for p in paths if p.exists()]


@dataclass
class ReplaySpec:
    rom: Path
    frames: int
    schedule: dict
    tail: int | None  # score only the last `tail` frames (None = all)


# Prefer the fetched c-sp suite; fall back to the bundled SameBoy ROMs if not fetched.
REPLAYS = [ReplaySpec(p, 400, {}, None) for p in _exists([
    TR / "blargg/cpu_instrs/cpu_instrs.gb",  # scrolls its output as it runs = moving content
])] or [ReplaySpec(ACTIONS / "dmg-acid2.gb", 200, {}, None)]

AUDIO_REPLAYS = [ReplaySpec(p, 120, {}, None) for p in _exists([
    TR / "blargg/dmg_sound/dmg_sound.gb",
])] or [ReplaySpec(ACTIONS / "dmg_sound-2.gb", 120, {}, None)]

# Procedural: tests that settle to a static pass/fail screen (good screenshot discriminators).
PROC_ROMS = _exists([
    TR / "dmg-acid2/dmg-acid2.gb",
    TR / "blargg/cpu_instrs/individual/01-special.gb",
    TR / "blargg/cpu_instrs/individual/06-ld r,r.gb",
    TR / "blargg/instr_timing/instr_timing.gb",
    TR / "blargg/mem_timing/mem_timing.gb",
]) or [ACTIONS / "dmg-acid2.gb", ACTIONS / "oam_bug-2.gb", ACTIONS / "dmg_sound-2.gb"]

EmuFactory = Callable[[], object]


def grade(candidate: EmuFactory, label: str, oracle: EmuFactory = OracleEmu) -> dict:
    # --- replay ---
    replay_scores = []
    for spec in REPLAYS:
        rom = spec.rom.read_bytes()
        cand = drive(candidate(), rom, spec.frames, spec.schedule)
        ref = _ocache("replay", rom, spec.frames, spec.schedule,
                      lambda: drive(oracle(), rom, spec.frames, spec.schedule))
        res, _offset = score_replay_aligned(cand, ref)
        replay_scores.append(res.score)
    replay = float(np.mean(replay_scores)) if replay_scores else 0.0

    # --- procedural (oracle final frames cached) ---
    oracle_finals = {}
    for p in PROC_ROMS:
        rb = Path(p).read_bytes()
        oracle_finals[Path(p).name] = _ocache(
            "proc", rb, PROC_FRAMES, {}, lambda rb=rb: final_frame(oracle(), rb, PROC_FRAMES))
    proc = score_procedural(candidate, oracle, PROC_ROMS, oracle_finals=oracle_finals)

    # --- audio (0 if the candidate produces none) ---
    audio_scores = []
    for spec in AUDIO_REPLAYS:
        rom = spec.rom.read_bytes()
        ca = capture_audio(candidate(), rom, spec.frames)
        ra = _ocache("audio", rom, spec.frames, {},
                     lambda: capture_audio(oracle(), rom, spec.frames))
        audio_scores.append(0.0 if ca.shape[0] == 0 else score_audio(ca, ra).score)
    audio = float(np.mean(audio_scores)) if audio_scores else 0.0

    detail = {
        "procedural": [
            {"name": r.name, "defect": round(r.defect, 6), "pass": r.passed}
            for r in proc.results
        ]
    }
    return build_report(label, replay, audio, proc.score, detail)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    target = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "scores.json"
    if target == "oracle":
        candidate, label = OracleEmu, "oracle (self-play)"
    else:
        wasm = Path(target)
        candidate, label = (lambda: WasmEmu(str(wasm))), wasm.name
    report = grade(candidate, label)
    write_scores(report, out)
    print_summary(report)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
