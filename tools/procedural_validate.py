"""Validate the procedural section: oracle-self = 100%, blank = 0%, rboy = realistic."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from runner import WasmEmu  # noqa: E402
from procedural_roms import score_procedural  # noqa: E402

WASM = ROOT / "reference/known-good/target/wasm32-unknown-unknown/release/gb_emu.wasm"
ACTIONS = ROOT / "oracle/SameBoy/.github/actions"
ROMS = [ACTIONS / "dmg-acid2.gb", ACTIONS / "oam_bug-2.gb", ACTIONS / "dmg_sound-2.gb"]


class NoiseEmu:
    """A broken emulator that renders random noise (can't accidentally match any screen)."""
    def __init__(self): self.rng = np.random.default_rng(0)
    def load(self, rom, boot_rom=None): pass
    def reset(self): pass
    def set_keys(self, m): pass
    def run_frame(self): pass
    def framebuffer(self):
        f = self.rng.integers(0, 256, (144, 160, 4), dtype=np.uint8); f[..., 3] = 255; return f
    def audio(self): return np.zeros((0, 2), np.int16)


def show(label, res):
    print(f"\n{label}: score={res.score:.3f} ({sum(r.passed for r in res.results)}/{res.n})")
    for r in res.results:
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.name:<18} defect={r.defect:.4f}")


oracle = lambda: OracleEmu()
rboy = lambda: WasmEmu(str(WASM))
noise = lambda: NoiseEmu()

ref = score_procedural(oracle, oracle, ROMS)
rb = score_procedural(rboy, oracle, ROMS)
bk = score_procedural(noise, oracle, ROMS)

show("oracle vs oracle (reference)", ref)
show("rboy vs oracle (known-good)", rb)
show("noise vs oracle (broken)", bk)

assert ref.score == 1.0, "oracle self-play must pass all"
assert bk.score == 0.0, "noise must pass none"
print("\nPASS: reference=1.0, broken=0.0, rboy realistic.")
