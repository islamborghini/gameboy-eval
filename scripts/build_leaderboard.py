"""Aggregate per-candidate scores.json into leaderboard/leaderboard.json.

Reads every leaderboard/results/*.json (each a grader report) and emits a ranked table the
static site renders.

    python scripts/build_leaderboard.py
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "leaderboard/results"
OUT = ROOT / "leaderboard/leaderboard.json"


def main() -> None:
    entries = []
    for f in sorted(RESULTS.glob("*.json")):
        d = json.loads(f.read_text())
        entries.append({
            "name": f.stem,
            "overall": d["overall"],
            "band": d["band"],
            "sections": d["sections"],
        })
    entries.sort(key=lambda e: e["overall"], reverse=True)
    OUT.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%d"),
        "weights": {"replay": 0.60, "audio": 0.20, "procedural": 0.20},
        "entries": entries,
    }, indent=2))
    print(f"wrote {OUT} ({len(entries)} entries)")
    for e in entries:
        print(f"  {e['overall']:.4f}  {e['band']:<28} {e['name']}")


if __name__ == "__main__":
    main()
