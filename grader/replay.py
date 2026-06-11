"""Replay scoring — the "almost the same almost everywhere" SSIM pipeline.

Candidate and reference are run in lockstep on the same recorded inputs; each frame gets a
structural-similarity score and we average. The metric rewards human-perceived playability,
not bit-equality (two good emulators are never pixel-identical).

Pipeline (GBA-Eval validated defaults; see EMU-EVAL-DESIGN.md sec 3.4):
  1. color-normalize: 5-bit quantize -> BT.601 luma
  2. 8x8 block SSIM -> defect = 1 - SSIM
  3. per-block perceptual floor 0.15
  4. blank-frame gate -> defect 1.0
  5. adaptive tau = 90th pct of moving consecutive-reference-frame defects, clamp [0.005,0.35]
  6. per-frame score 1/(1+(d/tau)^4); replay = mean over frames
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

L = 255.0
C1 = (0.01 * L) ** 2
C2 = (0.03 * L) ** 2

BLOCK = 8
FLOOR = 0.15
TAU_LO, TAU_HI = 0.005, 0.35
HILL = 4
MOVE_EPS = 1.0  # mean |delta-luma| above which a reference frame counts as "moving"


def luma(rgba: np.ndarray) -> np.ndarray:
    """uint8 [H,W,4] RGBA -> float [H,W] BT.601 luma after 5-bit color quantization."""
    q = ((rgba[..., :3] >> 3) << 3).astype(np.float32)
    return 0.299 * q[..., 0] + 0.587 * q[..., 1] + 0.114 * q[..., 2]


def _blocks(lum: np.ndarray, bs: int = BLOCK) -> np.ndarray:
    h, w = lum.shape
    gh, gw = h // bs, w // bs
    return (
        lum[: gh * bs, : gw * bs]
        .reshape(gh, bs, gw, bs)
        .transpose(0, 2, 1, 3)
        .reshape(gh, gw, bs * bs)
    )


def block_ssim_defect(la: np.ndarray, lb: np.ndarray, bs: int = BLOCK) -> np.ndarray:
    """Classical per-block SSIM on luma -> defect grid [gh,gw] in [0,1]."""
    a, b = _blocks(la, bs), _blocks(lb, bs)
    mua, mub = a.mean(-1), b.mean(-1)
    va, vb = a.var(-1), b.var(-1)
    cov = ((a - mua[..., None]) * (b - mub[..., None])).mean(-1)
    ssim = ((2 * mua * mub + C1) * (2 * cov + C2)) / (
        (mua**2 + mub**2 + C1) * (va + vb + C2)
    )
    return np.clip(1.0 - ssim, 0.0, 1.0)


def is_blank(rgba: np.ndarray, frac: float = 0.999) -> bool:
    """True if >= `frac` of pixels share a single color."""
    flat = rgba[..., :3].reshape(-1, 3)
    # pack RGB into one int for a fast mode count
    packed = (flat[:, 0].astype(np.uint32) << 16) | (
        flat[:, 1].astype(np.uint32) << 8
    ) | flat[:, 2].astype(np.uint32)
    counts = np.bincount(packed)
    return counts.max() / packed.shape[0] >= frac


def frame_defect(cand: np.ndarray, ref: np.ndarray, bs: int = BLOCK,
                 floor: float = FLOOR) -> float:
    if is_blank(cand) and not is_blank(ref):
        return 1.0
    d = block_ssim_defect(luma(cand), luma(ref), bs)
    d = np.where(d < floor, 0.0, d)
    return float(d.mean())


def adaptive_tau(ref_frames: list[np.ndarray], bs: int = BLOCK,
                 floor: float = FLOOR) -> float:
    """90th percentile of per-frame defects between consecutive *moving* reference frames."""
    lums = [luma(f) for f in ref_frames]
    defects = []
    for prev, cur in zip(lums, lums[1:]):
        if np.abs(cur - prev).mean() <= MOVE_EPS:
            continue
        d = block_ssim_defect(prev, cur, bs)
        d = np.where(d < floor, 0.0, d)
        defects.append(float(d.mean()))
    if not defects:
        return TAU_LO
    return float(np.clip(np.percentile(defects, 90), TAU_LO, TAU_HI))


@dataclass
class ReplayResult:
    score: float
    tau: float
    n_frames: int
    per_frame: list[float]


def score_replay(cand_frames: list[np.ndarray], ref_frames: list[np.ndarray],
                 bs: int = BLOCK, floor: float = FLOOR) -> ReplayResult:
    assert len(cand_frames) == len(ref_frames), "frame count mismatch"
    tau = adaptive_tau(ref_frames, bs, floor)
    per_frame = []
    for c, r in zip(cand_frames, ref_frames):
        d = frame_defect(c, r, bs, floor)
        per_frame.append(1.0 / (1.0 + (d / tau) ** HILL))
    return ReplayResult(
        score=float(np.mean(per_frame)) if per_frame else 0.0,
        tau=tau,
        n_frames=len(per_frame),
        per_frame=per_frame,
    )


def drive(emu, rom: bytes, n_frames: int, schedule: dict[int, int] | None = None,
          boot_rom: bytes | None = None) -> list[np.ndarray]:
    """Run an Emulator through a replay and capture every frame (uint8 [144,160,4] RGBA).

    `schedule` maps frame index -> joypad mask (held until the next change).
    """
    emu.load(rom, boot_rom)
    emu.reset()
    schedule = schedule or {}
    mask = 0
    frames = []
    for i in range(n_frames):
        if i in schedule:
            mask = schedule[i]
        emu.set_keys(mask)
        emu.run_frame()
        frames.append(emu.framebuffer().copy())
    return frames
