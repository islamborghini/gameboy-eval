"""M2 gate: drive the SameBoy oracle through OracleEmu, dump a frame, check determinism.

    .venv/bin/python tools/oracle_smoke.py [rom] [frames] [out.png]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
from sameboy import OracleEmu  # noqa: E402

rom_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    ROOT / "oracle/SameBoy/.github/actions/dmg-acid2.gb"
)
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 220
out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/oracle_frame.png")


def run(n: int) -> np.ndarray:
    emu = OracleEmu()
    emu.load(rom_path.read_bytes())
    emu.reset()
    emu.set_keys(0)
    for _ in range(n):
        emu.run_frame()
    return emu, emu.framebuffer()


emu, fb = run(frames)
rgb = fb[..., :3]
print(f"rom            = {rom_path.name}")
print(f"fps            = {emu.core.fps:.3f}")
print(f"sample_rate    = {emu.core.sample_rate:.0f}")
print(f"pixel_format   = {emu.core.pixel_format} (1 = XRGB8888)")
print(f"framebuffer    = {fb.shape} {fb.dtype}")
print(f"luma mean      = {rgb.mean():.1f}")
print(f"unique colors  = {len(np.unique(rgb.reshape(-1, 3), axis=0))}")
print(f"audio frames   = {emu.audio().shape[0]}")

Image.fromarray(fb, "RGBA").save(out)
print(f"saved          = {out}")

_, fb2 = run(frames)
print(f"deterministic  = {bool(np.array_equal(fb, fb2))}")
