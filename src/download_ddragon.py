import json
import os
from pathlib import Path

import requests


DD_URL = "https://ddragon.leagueoflegends.com"
OUT_DIR = Path("data/raw/ddragon")


def get_latest_version() -> str:
    versions_url = f"{DD_URL}/api/versions.json"
    r = requests.get(versions_url, timeout=30)
    r.raise_for_status()
    versions = r.json()
    if not versions:
        raise RuntimeError("No versions returned from Data Dragon.")
    return versions[0]


def download_json(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    out_path.write_text(r.text, encoding="utf-8")
    print(f"Saved: {out_path}")


def main() -> None:
    version = get_latest_version()
    print(f"Latest Data Dragon version: {version}")

    # Champion full data (all champs + tags, stats, etc.)
    champ_url = f"{DD_URL}/cdn/{version}/data/en_US/championFull.json"
    download_json(champ_url, OUT_DIR / version / "championFull.json")

    # Items data
    item_url = f"{DD_URL}/cdn/{version}/data/en_US/item.json"
    download_json(item_url, OUT_DIR / version / "item.json")

    # Small metadata file so you know what version you downloaded
    meta = {"ddragon_version": version}
    meta_path = OUT_DIR / "ddragon_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved: {meta_path}")

    print("\nDone downloading Data Dragon data.")
    print(f"Files are in: {OUT_DIR / version}")


if __name__ == "__main__":
    main()