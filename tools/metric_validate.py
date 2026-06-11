"""M3a gate: validate the replay-SSIM metric WITHOUT any model.

Proves the grader (a) scores identical streams ~1.0 and (b) detects failure on
deliberately-perturbed streams (timing shift, blanking, noise, wrong ROM).
Motion for the adaptive-tau comes for free from the boot-logo scroll in the first frames.

    .venv/bin/python tools/metric_validate.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from replay import drive, score_replay, is_blank  # noqa: E402

ROMS = ROOT / "oracle/SameBoy/.github/actions"
N = 150
rom = (ROMS / "dmg-acid2.gb").read_bytes()
other = (ROMS / "oam_bug-2.gb").read_bytes()

ref = drive(OracleEmu(), rom, N)            # reference stream (incl. boot scroll)
cand = drive(OracleEmu(), rom, N)           # identical second run


def shifted(frames):
    return [frames[0]] + frames[:-1]        # 1-frame timing desync


def blanked(frames, every=4):
    out = []
    for i, f in enumerate(frames):
        if i % every == 0:
            out.append(np.full_like(f, 255))  # solid white frame
        else:
            out.append(f)
    return out


def noisy(frames, sigma=40):
    rng = np.random.default_rng(0)
    out = []
    for f in frames:
        n = rng.normal(0, sigma, f[..., :3].shape)
        g = np.clip(f[..., :3].astype(np.float32) + n, 0, 255).astype(np.uint8)
        h = f.copy(); h[..., :3] = g
        out.append(h)
    return out


cases = {
    "identical (oracle vs oracle)": cand,
    "1-frame timing shift": shifted(ref),
    "blank every 4th frame": blanked(ref),
    "gaussian noise sigma=40": noisy(ref),
    "wrong ROM (oam_bug)": drive(OracleEmu(), other, N),
}

print(f"{'case':<32} {'score':>7}  {'tau':>6}  notes")
print("-" * 70)
results = {}
for name, c in cases.items():
    r = score_replay(c, ref)
    results[name] = r
    print(f"{name:<32} {r.score:>7.4f}  {r.tau:>6.4f}")

# --- assertions: the metric must agree-with-itself AND detect failure ---
ident = results["identical (oracle vs oracle)"].score
assert ident > 0.999, f"identical should be ~1.0, got {ident}"

# every perturbation must be strictly detected (below a perfect run)
for name in cases:
    if name.startswith("identical"):
        continue
    assert results[name].score < ident, f"{name} not detected (>= identical)"

# severe corruption collapses toward 0
assert results["gaussian noise sigma=40"].score < 0.05, "noise should ~0"

# blank-gate: blanked candidate frames against a NON-blank reference must pin to ~0
# (blank-vs-blank during the boot screen is legitimately identical and stays 1.0)
blank_pf = results["blank every 4th frame"].per_frame
pinned = [blank_pf[i] for i in range(0, N, 4) if not is_blank(ref[i])]
# a fully-defective frame scores 1/(1+(1/tau)^4) -> ~0 but never literally 0
assert pinned and max(pinned) < 1e-3, f"blanked frames not pinned: max={max(pinned)}"

print("-" * 70)
print("PASS: identical ~1.0, all perturbations detected, blank frames pinned, noise ~0.")
