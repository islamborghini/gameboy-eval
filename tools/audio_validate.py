"""Validate the audio section: oracle-vs-oracle ~1.0, perturbations clearly lower."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "grader"))
from sameboy import OracleEmu  # noqa: E402
from audio import capture_audio, score_audio  # noqa: E402

rom = (ROOT / "oracle/SameBoy/.github/actions/dmg_sound-2.gb").read_bytes()
N = 120

ref = capture_audio(OracleEmu(), rom, N)
cand = capture_audio(OracleEmu(), rom, N)  # identical second run
print(f"captured {ref.shape[0]} stereo samples; energy={np.abs(ref).mean():.1f}")

rng = np.random.default_rng(0)
noisy = np.clip(ref.astype(np.int32) + rng.normal(0, 3000, ref.shape), -32768, 32767).astype(np.int16)
silent = np.zeros_like(ref)

cases = {
    "identical (oracle vs oracle)": cand,
    "added noise": noisy,
    "silence": silent,
}
print(f"\n{'case':<32} {'score':>7}  {'tau':>6}")
print("-" * 50)
results = {}
for name, c in cases.items():
    r = score_audio(c, ref)
    results[name] = r
    print(f"{name:<32} {r.score:>7.4f}  {r.tau:>6.4f}")

ident = results["identical (oracle vs oracle)"].score
assert ident > 0.99, f"identical audio should be ~1.0, got {ident}"
assert results["silence"].score < ident, "silence must be detected"
assert results["added noise"].score < ident, "noise must be detected"
print("-" * 50)
print("PASS: identical ~1.0, perturbations detected.")
