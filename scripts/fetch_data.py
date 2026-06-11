"""Fetch open Game Boy test ROMs.

Downloads the c-sp/game-boy-test-roms release bundle (Blargg, Mooneye, dmg/cgb-acid2,
Mealybug, ...) into data/test-roms/ (git-ignored). These are published for emulator testing;
see NOTICE for attribution. Several (e.g. Blargg's cpu_instrs) scroll their output as they
run, giving moving content for the replay section as well as a procedural corpus.

    python scripts/fetch_data.py
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/test-roms"
REPO = "c-sp/game-boy-test-roms"


def latest_zip_url(repo: str) -> tuple[str, str]:
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    data = json.loads(urllib.request.urlopen(api, timeout=60).read())
    for asset in data["assets"]:
        if asset["name"].endswith(".zip"):
            return asset["browser_download_url"], asset["name"]
    raise RuntimeError(f"no .zip asset in latest release of {repo}")


def main() -> None:
    url, name = latest_zip_url(REPO)
    print(f"downloading {name} ...")
    blob = urllib.request.urlopen(url, timeout=300).read()
    print(f"  {len(blob)/1e6:.1f} MB; extracting -> {DEST}")
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(DEST)
    roms = list(DEST.rglob("*.gb")) + list(DEST.rglob("*.gbc"))
    print(f"done: {len(roms)} ROMs under {DEST}")


if __name__ == "__main__":
    main()
