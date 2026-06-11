"""Validate boot-offset alignment: recover a known shift and restore the score.

Simulates a candidate that runs N frames ahead of the oracle (as a no-boot emulator does),
using the boot-logo motion as real moving content.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from replay import drive, score_replay, score_replay_aligned, align_offset  # noqa: E402

rom = (ROOT / "oracle/SameBoy/.github/actions/dmg-acid2.gb").read_bytes()
SHIFT = 8  # small, so the probe window lands in the boot-logo motion (acid2 is static by ~f40)
ref = drive(OracleEmu(), rom, 150)
cand = ref[SHIFT:]  # candidate runs SHIFT frames ahead (no boot animation)

recovered = align_offset(cand, ref)
naive = score_replay(cand[: len(cand)], ref[: len(cand)]).score
aligned, s = score_replay_aligned(cand, ref)

print(f"true shift      = {SHIFT}")
print(f"recovered shift = {recovered}")
print(f"naive score (no alignment) = {naive:.4f}")
print(f"aligned score              = {aligned.score:.4f}  (offset {s})")

assert recovered == SHIFT, f"alignment should recover {SHIFT}, got {recovered}"
assert aligned.score > 0.999, f"aligned identical content should be ~1.0, got {aligned.score}"
assert aligned.score > naive, "alignment must improve the misaligned score"
print("PASS: offset recovered, alignment restores the score.")
