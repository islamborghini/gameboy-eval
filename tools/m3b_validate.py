"""M3b gate: a known-good WASM candidate (rboy) must score ~1.0 vs the SameBoy oracle.

rboy has no boot animation (it starts post-boot) while SameBoy runs the boot ROM, so we
compare the *settled* tail of each stream (dmg-acid2 is static once rendered). A high score
proves the full candidate path (rboy -> wasm -> WasmEmu -> framebuffer) works AND that two
independent accurate emulators are scored ~1.0 by the metric.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from runner import WasmEmu  # noqa: E402
from replay import drive, score_replay, frame_defect, luma  # noqa: E402

WASM = ROOT / "reference/known-good/target/wasm32-unknown-unknown/release/gb_emu.wasm"
rom = (ROOT / "oracle/SameBoy/.github/actions/dmg-acid2.gb").read_bytes()
N, TAIL = 200, 80

rb = drive(WasmEmu(str(WASM)), rom, N)
orc = drive(OracleEmu(), rom, N)

Image.fromarray(rb[-1], "RGBA").save("/tmp/rboy_acid2.png")
Image.fromarray(orc[-1], "RGBA").save("/tmp/oracle_acid2.png")

d = frame_defect(rb[-1], orc[-1])
exact = bool(np.array_equal(luma(rb[-1]), luma(orc[-1])))
print(f"settled-frame defect = {d:.6f}")
print(f"exact luma match     = {exact}")
print(f"rboy  unique colors  = {len(np.unique(rb[-1][..., :3].reshape(-1, 3), axis=0))}")
print(f"oracle unique colors = {len(np.unique(orc[-1][..., :3].reshape(-1, 3), axis=0))}")

res = score_replay(rb[-TAIL:], orc[-TAIL:])
print(f"M3b replay score (last {TAIL}) = {res.score:.4f}  tau={res.tau:.4f}")
print("PASS" if res.score >= 0.9 else "BELOW GATE (<0.9)")
