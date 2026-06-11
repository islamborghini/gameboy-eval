"""M4 gate: composite computed end-to-end; reference ~1.0, broken ~0, rboy realistic."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from runner import WasmEmu  # noqa: E402
from grade import grade  # noqa: E402
from report import print_summary  # noqa: E402

WASM = ROOT / "reference/known-good/target/wasm32-unknown-unknown/release/gb_emu.wasm"


class NoiseEmu:
    def __init__(self): self.rng = np.random.default_rng(0)
    def load(self, rom, boot_rom=None): pass
    def reset(self): pass
    def set_keys(self, m): pass
    def run_frame(self): pass
    def framebuffer(self):
        f = self.rng.integers(0, 256, (144, 160, 4), dtype=np.uint8); f[..., 3] = 255; return f
    def audio(self): return np.zeros((0, 2), np.int16)


oracle_rep = grade(OracleEmu, "oracle (self-play)")
rboy_rep = grade(lambda: WasmEmu(str(WASM)), "rboy (known-good)")
noise_rep = grade(lambda: NoiseEmu(), "noise (broken)")

for rep in (oracle_rep, rboy_rep, noise_rep):
    print_summary(rep)

assert oracle_rep["overall"] > 0.95, f"reference should be ~1.0, got {oracle_rep['overall']}"
assert noise_rep["overall"] < 0.10, f"broken should be ~0, got {noise_rep['overall']}"
print(f"\nPASS: reference={oracle_rep['overall']:.4f}, "
      f"rboy={rboy_rep['overall']:.4f}, broken={noise_rep['overall']:.4f}")
