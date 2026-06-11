"""Composite scoring, score bands, scores.json schema, and the terminal summary."""
from __future__ import annotations

import json
from pathlib import Path

WEIGHTS = {"replay": 0.60, "audio": 0.20, "procedural": 0.20}

# Composite score bands (EMU-EVAL-DESIGN.md sec 3.5). reference-vs-itself = 1.00.
BANDS = [
    (0.999, "Reference (indistinguishable)"),
    (0.85, "Near-reference"),
    (0.70, "Mostly playable"),
    (0.45, "Plays incorrectly"),
    (0.15, "Barely works"),
    (0.0, "Doesn't run"),
]


def composite(replay: float, audio: float, procedural: float) -> float:
    return (
        WEIGHTS["replay"] * replay
        + WEIGHTS["audio"] * audio
        + WEIGHTS["procedural"] * procedural
    )


def band(score: float) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "Doesn't run"


def build_report(candidate: str, replay: float, audio: float, procedural: float,
                 detail: dict | None = None) -> dict:
    overall = composite(replay, audio, procedural)
    return {
        "candidate": candidate,
        "overall": round(overall, 6),
        "band": band(overall),
        "weights": WEIGHTS,
        "sections": {
            "replay": round(replay, 6),
            "audio": round(audio, 6),
            "procedural": round(procedural, 6),
        },
        "detail": detail or {},
    }


def write_scores(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2))


def print_summary(report: dict) -> None:
    s = report["sections"]
    print("=" * 60)
    print(f"  candidate : {report['candidate']}")
    print(f"  OVERALL   : {report['overall']:.4f}   [{report['band']}]")
    print("-" * 60)
    print(f"  replay     (x{WEIGHTS['replay']:.2f}) : {s['replay']:.4f}")
    print(f"  audio      (x{WEIGHTS['audio']:.2f}) : {s['audio']:.4f}")
    print(f"  procedural (x{WEIGHTS['procedural']:.2f}) : {s['procedural']:.4f}")
    proc = report.get("detail", {}).get("procedural", [])
    if proc:
        print("-" * 60)
        for r in proc:
            print(f"    {'PASS' if r['pass'] else 'FAIL'}  {r['name']:<18} defect={r['defect']:.4f}")
    print("=" * 60)
