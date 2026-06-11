"""Audio section — log-mel spectrogram distance through the per-frame Hill-then-mean pipeline.

Mirrors the replay metric in the spectral domain: build a log-mel spectrogram for candidate
and reference, score each spectrogram column with 1/(1+(d/tau)^4) on a normalized per-column
distance, and average. The SameBoy oracle outputs at its native 2^21 Hz, so we decimate to
32768 Hz (a clean factor of 64) before the STFT.

(Functional v1; mel parameters get refined in M6 "audio polish".)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly, stft

NATIVE_SR = 2_097_152  # SameBoy libretro native audio rate (2^21)
TARGET_SR = 32_768     # decimate by exactly 64
N_FFT = 1024
HOP = 512
N_MELS = 64
EPS = 1e-8
HILL = 4
TAU_LO, TAU_HI = 0.01, 0.5


def to_mono(samples_i16: np.ndarray) -> np.ndarray:
    if samples_i16.size == 0:
        return np.zeros(0, np.float32)
    return samples_i16.astype(np.float32).mean(axis=1) / 32768.0


def decimate(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    return resample_poly(x, 1, NATIVE_SR // TARGET_SR)


def _mel_fb(sr: int, n_fft: int, n_mels: int) -> np.ndarray:
    fmax = sr / 2
    hz2mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    mel2hz = lambda m: 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    pts = mel2hz(np.linspace(hz2mel(0), hz2mel(fmax), n_mels + 2))
    bins = np.floor((n_fft // 2) * pts / fmax).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), np.float32)
    for m in range(1, n_mels + 1):
        lo, ce, hi = bins[m - 1], bins[m], bins[m + 1]
        if ce > lo:
            fb[m - 1, lo:ce] = (np.arange(lo, ce) - lo) / (ce - lo)
        if hi > ce:
            fb[m - 1, ce:hi] = (hi - np.arange(ce, hi)) / (hi - ce)
    return fb


_FB = _mel_fb(TARGET_SR, N_FFT, N_MELS)


def logmel(x: np.ndarray) -> np.ndarray:
    if x.size < N_FFT:
        x = np.pad(x, (0, N_FFT - x.size))
    _, _, z = stft(x, fs=TARGET_SR, nperseg=N_FFT, noverlap=N_FFT - HOP)
    return np.log(_FB @ np.abs(z) + EPS)  # [n_mels, frames]


def _col_dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    num = np.linalg.norm(a - b, axis=0)
    den = np.linalg.norm(a, axis=0) + np.linalg.norm(b, axis=0) + EPS
    return np.clip(num / den, 0.0, 1.0)


def adaptive_tau(ref_logmel: np.ndarray) -> float:
    if ref_logmel.shape[1] < 2:
        return TAU_LO
    d = _col_dist(ref_logmel[:, :-1], ref_logmel[:, 1:])
    moving = d[d > 1e-4]
    if moving.size == 0:
        return TAU_LO
    return float(np.clip(np.percentile(moving, 90), TAU_LO, TAU_HI))


@dataclass
class AudioResult:
    score: float
    tau: float
    n_cols: int


def score_audio(cand_i16: np.ndarray, ref_i16: np.ndarray) -> AudioResult:
    a = logmel(decimate(to_mono(cand_i16)))
    b = logmel(decimate(to_mono(ref_i16)))
    n = min(a.shape[1], b.shape[1])
    if n == 0:
        return AudioResult(0.0, TAU_LO, 0)
    a, b = a[:, :n], b[:, :n]
    tau = adaptive_tau(b)
    d = _col_dist(a, b)
    scores = 1.0 / (1.0 + (d / tau) ** HILL)
    return AudioResult(float(scores.mean()), tau, n)


def capture_audio(emu, rom: bytes, n_frames: int, schedule: dict[int, int] | None = None,
                  boot_rom: bytes | None = None) -> np.ndarray:
    """Drive an Emulator and concatenate per-frame audio into one int16 [n,2] buffer."""
    emu.load(rom, boot_rom)
    emu.reset()
    schedule = schedule or {}
    mask = 0
    chunks = []
    for i in range(n_frames):
        if i in schedule:
            mask = schedule[i]
        emu.set_keys(mask)
        emu.run_frame()
        a = emu.audio()
        if a.size:
            chunks.append(a)
    return np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 2), np.int16)
