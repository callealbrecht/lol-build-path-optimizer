import json
from pathlib import Path

import pandas as pd

DD_META = Path("data/raw/ddragon/ddragon_meta.json")
TIMELINES_PATH = Path("data/raw/timelines.jsonl")

PARTICIPANTS_PATH = Path("data/processed/participants.parquet")
OUT_PATH = Path("data/processed/build_steps.csv")

# Exclude common non-build items (MVP list; can expand later)
EXCLUDE_ITEM_IDS = {
    3340, 3363, 3364,  # warding totem / farsight / oracle
    2055,              # control ward
    2003, 2010, 2031,  # potions/biscuits etc.
}


def load_item_depth():
    meta = json.loads(DD_META.read_text(encoding="utf-8"))
    version = meta["ddragon_version"]
    item_path = Path(f"data/raw/ddragon/{version}/item.json")
    item_json = json.loads(item_path.read_text(encoding="utf-8"))["data"]

    depth = {}
    for item_id_str, info in item_json.items():
        depth[int(item_id_str)] = int(info.get("depth", 0))
    return depth


def is_completed_item(item_id: int, depth_map: dict[int, int]) -> bool:
    if item_id in EXCLUDE_ITEM_IDS:
        return False
    if item_id <= 0:
        return False
    # MVP heuristic: depth>=3 is usually a completed item
    return depth_map.get(item_id, 0) >= 3


def main():
    if not TIMELINES_PATH.exists():
        raise FileNotFoundError(
            "Missing data/raw/timelines.jsonl. Run: python src/fetch_timelines.py"
        )

    depth_map = load_item_depth()

    # (matchId, puuid) -> [step1, step2, step3]
    steps_map = {}

    with TIMELINES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            tl = json.loads(line)
            meta = tl.get("metadata", {})
            info = tl.get("info", {})

            match_id = meta.get("matchId")
            puuids = meta.get("participants", [])  # index 0..9 => participantId 1..10
            frames = info.get("frames", [])

            if not match_id or not puuids or not frames:
                continue

            per_pid_steps = {pid: [] for pid in range(1, 11)}
            acquired = {pid: set() for pid in range(1, 11)}

            for fr in frames:
                for ev in fr.get("events", []):
                    et = ev.get("type")
                    if et not in ("ITEM_PURCHASED", "ITEM_UNDO"):
                        continue

                    pid = ev.get("participantId")
                    if pid not in per_pid_steps:
                        continue

                    if et == "ITEM_UNDO":
                        # For MVP we ignore undos (keeps extraction simple)
                        continue

                    item_id = int(ev.get("itemId", 0))
                    if not is_completed_item(item_id, depth_map):
                        continue

                    if item_id in acquired[pid]:
                        continue

                    per_pid_steps[pid].append(item_id)
                    acquired[pid].add(item_id)

            # map participantId -> puuid and store first 3 steps
            for pid in range(1, 11):
                if pid - 1 >= len(puuids):
                    continue
                puuid = puuids[pid - 1]
                steps = per_pid_steps[pid][:3]
                if not steps:
                    continue
                steps_map[(match_id, puuid)] = steps

    # Build steps dataframe
    rows = []
    for (match_id, puuid), s in steps_map.items():
        rows.append({
            "matchId": match_id,
            "puuid": puuid,
            "step1": s[0] if len(s) > 0 else None,
            "step2": s[1] if len(s) > 1 else None,
            "step3": s[2] if len(s) > 2 else None,
        })
    steps_df = pd.DataFrame(rows)

    # Load participant context and merge
    parts = pd.read_parquet(PARTICIPANTS_PATH)
    parts["patch"] = parts["patch"].astype(str)

    merged = parts.merge(steps_df, on=["matchId", "puuid"], how="inner")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_PATH, index=False)

    print(f"Extracted build steps for {len(steps_df)} players.")
    print(f"Merged dataset rows: {len(merged)}")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()