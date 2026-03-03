import json
import os
from pathlib import Path
from collections import Counter, defaultdict
from teamcomp_counters import load_ddragon_maps, suggest_situational

import pandas as pd


DATA_PATH = "data/processed/participants.csv"
DD_META = Path("data/raw/ddragon/ddragon_meta.json")

TOPN_BASELINE = 10

# thresholds per fallback level (specific -> general)
MIN_GAMES_L1 = 15  # (patch, role, champ, opp)
MIN_GAMES_L2 = 25  # (role, champ, opp)
MIN_GAMES_L3 = 40  # (champ, opp)

ALPHA = 0.8  # strength of re-ranking


def load_item_names() -> dict[int, str]:
    meta = json.loads(DD_META.read_text(encoding="utf-8"))
    version = meta["ddragon_version"]
    item_path = Path(f"data/raw/ddragon/{version}/item.json")
    item_json = json.loads(item_path.read_text(encoding="utf-8"))
    data = item_json["data"]
    out = {}
    for item_id_str, info in data.items():
        out[int(item_id_str)] = info.get("name", item_id_str)
    return out


def load_df():
    df = pd.read_csv(DATA_PATH)

    # Normalize types so lookups work reliably
    df["patch"] = df["patch"].astype(str)              # <-- important
    df["championId"] = df["championId"].astype(int)
    df["opponentChampionId"] = pd.to_numeric(df["opponentChampionId"], errors="coerce")

    for i in range(6):
        df[f"item{i}"] = df[f"item{i}"].replace(0, None)

    df = df[df["role"].isin(["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"])].copy()
    return df


def baseline_items(df):
    base = {}
    grouped = df.groupby(["patch", "role", "championId"])
    for key, g in grouped:
        c = Counter()
        for _, r in g.iterrows():
            items = [r[f"item{i}"] for i in range(6)]
            c.update([x for x in items if pd.notna(x)])
        base[key] = [it for it, _ in c.most_common(TOPN_BASELINE)]
    return base


def build_matchup_tables(df):
    item_cols = [f"item{i}" for i in range(6)]

    def build(keys):
        table = {}
        for key, g in df.groupby(keys):
            games = len(g)
            base_wr = g["win"].mean()

            ig = defaultdict(int)
            iw = defaultdict(int)

            for _, r in g.iterrows():
                w = int(r["win"])
                for it in [r[c] for c in item_cols]:
                    if pd.isna(it):
                        continue
                    ig[it] += 1
                    iw[it] += w

            item_wr = {it: (cnt, iw[it] / cnt) for it, cnt in ig.items()}
            table[key] = {"games": games, "base_wr": base_wr, "item_wr": item_wr}
        return table

    l1 = build(["patch", "role", "championId", "opponentChampionId"])
    l2 = build(["role", "championId", "opponentChampionId"])
    l3 = build(["championId", "opponentChampionId"])
    return l1, l2, l3


def rerank(candidates, stats, base_wr, min_games):
    scored = []
    for it in candidates:
        it_stats = stats["item_wr"].get(it)
        if not it_stats:
            scored.append((0.0, it))
            continue

        g_with, wr_with = it_stats
        delta = wr_with - base_wr

        # confidence grows with sample size; capped at 1
        confidence = min(1.0, g_with / (min_games * 2))
        score = ALPHA * delta * confidence
        scored.append((score, it))

    scored.sort(reverse=True, key=lambda x: x[0])
    return [it for _, it in scored]


def recommend(df, base, l1, l2, l3, patch, role, champ, opp):
    base_key = (patch, role, champ)
    if base_key not in base:
        return [], ["No baseline data for this champ/role/patch."]

    candidates = base[base_key]
    if opp is None:
        return candidates[:5], ["No lane opponent detected for this role (using baseline)."]

    # Try level 1
    key1 = (patch, role, champ, opp)
    s1 = l1.get(key1)
    if s1 and s1["games"] >= MIN_GAMES_L1:
        ranked = rerank(candidates, s1, s1["base_wr"], MIN_GAMES_L1)
        return ranked[:5], [f"Matchup-aware (patch+role) using n={s1['games']} Emerald+ games."]

    # Try level 2
    key2 = (role, champ, opp)
    s2 = l2.get(key2)
    if s2 and s2["games"] >= MIN_GAMES_L2:
        ranked = rerank(candidates, s2, s2["base_wr"], MIN_GAMES_L2)
        return ranked[:5], [f"Matchup-aware (role) using n={s2['games']} Emerald+ games (patch-agnostic)."]

    # Try level 3
    key3 = (champ, opp)
    s3 = l3.get(key3)
    if s3 and s3["games"] >= MIN_GAMES_L3:
        ranked = rerank(candidates, s3, s3["base_wr"], MIN_GAMES_L3)
        return ranked[:5], [f"Matchup-aware (champ vs champ) using n={s3['games']} Emerald+ games (role+patch-agnostic)."]

    return candidates[:5], [
        "Not enough direct matchup data yet — using baseline.",
        "Tip: download more matches to strengthen matchup statistics."
    ]


def main():
    item_names = load_item_names()
    df = load_df()

    base = baseline_items(df)
    l1, l2, l3 = build_matchup_tables(df)

    sample = df.sample(1, random_state=1).iloc[0]
    patch = str(sample["patch"])
    role = sample["role"]
    champ = int(sample["championId"])
    opp = int(sample["opponentChampionId"]) if pd.notna(sample["opponentChampionId"]) else None

    rec, why = recommend(df, base, l1, l2, l3, patch, role, champ, opp)

    champ_tags_map, item_name_map, item_exists = load_ddragon_maps()

    # enemies is stored as a string like "[64, 107, ...]" in CSV
    enemies = sample["enemies"]
    enemy_ids = json.loads(enemies.replace("'", '"')) if isinstance(enemies, str) else []

    situational, reasons = suggest_situational(enemy_ids, champ_tags_map, item_name_map, item_exists)

    print("\nCORE (baseline/matchup):")
    for it in rec:
        print(f"- {it}: {item_name_map.get(int(it), str(it))}")

    print("\nSITUATIONAL (teamcomp):")
    if situational:
        for s in situational:
            print("-", s)
    else:
        print("- No strong teamcomp counters detected.")

    print("\nWhy:")
    for w in why:
        print("-", w)
    for r in reasons:
        print("-", r)


if __name__ == "__main__":
    main()