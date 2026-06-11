"""Procedural section — self-checking GB test ROMs scored on final state.

Most test ROMs (Blargg, Mooneye, dmg-acid2, Mealybug) display their pass/fail result on
screen. Rather than depend on CPU-register / serial introspection (which the candidate ABI
deliberately does not expose), we score each ROM by comparing the candidate's *settled
final frame* to the oracle's: a ROM passes if the screens match (defect below threshold).
The oracle is ground truth, so this is deterministic and fair.

Pass rate over the suite = the procedural section score in [0,1].
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from replay import drive, frame_defect

# A candidate/oracle is built fresh per ROM (emulator instances are stateful).
EmuFactory = Callable[[], object]

# Run long enough that both candidate and oracle settle on their static result screen,
# so the candidate's lack of a boot animation (a ~60-frame head start) doesn't matter.
DEFAULT_FRAMES = 1000
PASS_THRESHOLD = 0.05  # floored final-frame defect at/below which the screens "match"


def final_frame(emu, rom: bytes, n_frames: int, boot_rom: bytes | None = None):
    return drive(emu, rom, n_frames, boot_rom=boot_rom)[-1]


@dataclass
class RomResult:
    name: str
    defect: float
    passed: bool


@dataclass
class ProceduralResult:
    score: float
    n: int
    results: list[RomResult]


def score_procedural(
    candidate: EmuFactory,
    oracle: EmuFactory,
    roms: list[str | Path],
    n_frames: int = DEFAULT_FRAMES,
    threshold: float = PASS_THRESHOLD,
    boot_rom: bytes | None = None,
    oracle_finals: dict[str, "object"] | None = None,
) -> ProceduralResult:
    """If `oracle_finals` (name -> settled oracle frame) is given, the oracle isn't re-run."""
    results: list[RomResult] = []
    for p in roms:
        p = Path(p)
        rom = p.read_bytes()
        cand = final_frame(candidate(), rom, n_frames, boot_rom)
        if oracle_finals is not None and p.name in oracle_finals:
            ref = oracle_finals[p.name]
        else:
            ref = final_frame(oracle(), rom, n_frames)
        d = frame_defect(cand, ref)
        results.append(RomResult(p.name, d, d <= threshold))
    score = sum(r.passed for r in results) / len(results) if results else 0.0
    return ProceduralResult(score=score, n=len(results), results=results)
