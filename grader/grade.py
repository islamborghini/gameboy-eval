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
from procedural_roms import score_procedural  # noqa: E402
from report import build_report, print_summary, write_scores  # noqa: E402

ACTIONS = ROOT / "oracle/SameBoy/.github/actions"


@dataclass
class ReplaySpec:
    rom: Path
    frames: int
    schedule: dict
    tail: int | None  # score only the last `tail` frames (None = all)


# Minimal M4 suite (bundled SameBoy test ROMs). Extend via scripts/fetch_data.py later.
REPLAYS = [ReplaySpec(ACTIONS / "dmg-acid2.gb", 200, {}, 80)]
AUDIO_REPLAYS = [ReplaySpec(ACTIONS / "dmg_sound-2.gb", 120, {}, None)]
PROC_ROMS = [ACTIONS / "dmg-acid2.gb", ACTIONS / "oam_bug-2.gb", ACTIONS / "dmg_sound-2.gb"]

EmuFactory = Callable[[], object]


def grade(candidate: EmuFactory, label: str, oracle: EmuFactory = OracleEmu) -> dict:
    # --- replay ---
    replay_scores = []
    for spec in REPLAYS:
        rom = spec.rom.read_bytes()
        cand = drive(candidate(), rom, spec.frames, spec.schedule)
        ref = drive(oracle(), rom, spec.frames, spec.schedule)
        res, _offset = score_replay_aligned(cand, ref)
        replay_scores.append(res.score)
    replay = float(np.mean(replay_scores)) if replay_scores else 0.0

    # --- procedural ---
    proc = score_procedural(candidate, oracle, PROC_ROMS)

    # --- audio (0 if the candidate produces none) ---
    audio_scores = []
    for spec in AUDIO_REPLAYS:
        rom = spec.rom.read_bytes()
        ca = capture_audio(candidate(), rom, spec.frames)
        ra = capture_audio(oracle(), rom, spec.frames)
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
