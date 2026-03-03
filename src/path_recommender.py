import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from src.champions import load_champion_maps, champion_name_to_id
from src.teamcomp_counters import load_ddragon_maps

DD_META = Path("data/raw/ddragon/ddragon_meta.json")
DATA_PATH = "data/processed/build_steps.csv"

ROLE_MAP = {
    "top": "TOP",
    "jg": "JUNGLE",
    "jungle": "JUNGLE",
    "mid": "MIDDLE",
    "middle": "MIDDLE",
    "adc": "BOTTOM",
    "bot": "BOTTOM",
    "bottom": "BOTTOM",
    "sup": "UTILITY",
    "support": "UTILITY",
    "utility": "UTILITY",
}

# Fallback thresholds
MIN_GAMES_L1 = 20  # (patch, role, champ, opp)
MIN_GAMES_L2 = 35  # (role, champ, opp)
MIN_GAMES_L3 = 60  # (champ, opp)

ALPHA = 0.9  # strength of matchup re-ranking


def load_item_names() -> dict[int, str]:
    meta = json.loads(DD_META.read_text(encoding="utf-8"))
    version = meta["ddragon_version"]
    item_path = Path(f"data/raw/ddragon/{version}/item.json")
    item_json = json.loads(item_path.read_text(encoding="utf-8"))["data"]
    return {int(k): v.get("name", k) for k, v in item_json.items()}


def load_df():
    df = pd.read_csv(DATA_PATH)
    df["patch"] = df["patch"].astype(str)
    df["championId"] = df["championId"].astype(int)
    df["opponentChampionId"] = pd.to_numeric(df["opponentChampionId"], errors="coerce")
    # steps may be floats because of NaNs
    for c in ["step1", "step2", "step3"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _baseline_for_step(df, step_col: str):
    """Top items per (patch, role, champ) for a given step."""
    base = {}
    g = df.dropna(subset=[step_col]).groupby(["patch", "role", "championId"])
    for key, grp in g:
        c = Counter(int(x) for x in grp[step_col].dropna().tolist())
        base[key] = [it for it, _ in c.most_common(10)]
    return base


def _matchup_tables_for_step(df, step_col: str):
    """Build 3 fallback tables for a given step."""
    def build(keys):
        table = {}
        gg = df.dropna(subset=[step_col, "opponentChampionId"]).groupby(keys)
        for key, grp in gg:
            games = len(grp)
            base_wr = grp["win"].mean()
            item_games = defaultdict(int)
            item_wins = defaultdict(int)

            for _, r in grp.iterrows():
                it = r[step_col]
                if pd.isna(it):
                    continue
                it = int(it)
                item_games[it] += 1
                item_wins[it] += int(r["win"])

            item_wr = {it: (cnt, item_wins[it] / cnt) for it, cnt in item_games.items()}
            table[key] = {"games": games, "base_wr": base_wr, "item_wr": item_wr}
        return table

    l1 = build(["patch", "role", "championId", "opponentChampionId"])
    l2 = build(["role", "championId", "opponentChampionId"])
    l3 = build(["championId", "opponentChampionId"])
    return l1, l2, l3


def _rerank(candidates, stats, min_games):
    base_wr = stats["base_wr"]
    scored = []
    for it in candidates:
        it_stats = stats["item_wr"].get(it)
        if not it_stats:
            scored.append((0.0, it))
            continue
        g_with, wr_with = it_stats
        delta = wr_with - base_wr
        conf = min(1.0, g_with / (min_games * 2))
        score = ALPHA * delta * conf
        scored.append((score, it))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [it for _, it in scored]


def recommend_step(step_base, step_l1, step_l2, step_l3, patch, role, champ, opp, already_picked=None):
    already_picked = set(already_picked or [])

    base_key = (patch, role, champ)
    candidates = step_base.get(base_key, [])
    candidates = [it for it in candidates if it not in already_picked]

    if not candidates:
        return None, "No baseline candidates for this step."

    if opp is None:
        return candidates[0], "No opponent provided → baseline."

    key1 = (patch, role, champ, opp)
    s1 = step_l1.get(key1)
    if s1 and s1["games"] >= MIN_GAMES_L1:
        ranked = _rerank(candidates, s1, MIN_GAMES_L1)
        return ranked[0], f"Matchup-aware L1 (patch+role), n={s1['games']}"

    key2 = (role, champ, opp)
    s2 = step_l2.get(key2)
    if s2 and s2["games"] >= MIN_GAMES_L2:
        ranked = _rerank(candidates, s2, MIN_GAMES_L2)
        return ranked[0], f"Matchup-aware L2 (role), n={s2['games']}"

    key3 = (champ, opp)
    s3 = step_l3.get(key3)
    if s3 and s3["games"] >= MIN_GAMES_L3:
        ranked = _rerank(candidates, s3, MIN_GAMES_L3)
        return ranked[0], f"Matchup-aware L3 (champ vs champ), n={s3['games']}"

    return candidates[0], "Baseline (not enough matchup data)."


def main():
    print("Loading build-step dataset and building step models...")
    df = load_df()

    item_names = load_item_names()
    name_to_id, id_to_name = load_champion_maps()
    champ_tags_map, item_name_map, item_exists = load_ddragon_maps()

    # Build baseline + matchup tables for each step
    base1 = _baseline_for_step(df, "step1")
    base2 = _baseline_for_step(df, "step2")
    base3 = _baseline_for_step(df, "step3")

    l1_1, l2_1, l3_1 = _matchup_tables_for_step(df, "step1")
    l1_2, l2_2, l3_2 = _matchup_tables_for_step(df, "step2")
    l1_3, l2_3, l3_3 = _matchup_tables_for_step(df, "step3")

    print("Ready.\n")

    # Interactive loop
    while True:
        patch = input("Patch (e.g. 15.6) or ENTER for most common: ").strip()
        if not patch:
            patch = str(df["patch"].mode().iloc[0])

        role_in = input("Role (top/jg/mid/adc/sup): ").strip().lower()
        role = ROLE_MAP.get(role_in)
        if not role:
            print("Unknown role.\n")
            continue

        champ_name = input("Your champion (e.g. Rengar): ").strip()
        champ = champion_name_to_id(champ_name, name_to_id)

        opp_name = input("Lane opponent (or ENTER to skip): ").strip()
        opp = champion_name_to_id(opp_name, name_to_id) if opp_name else None

        enemies_in = input("Enemy team champs (comma-separated names): ").strip()
        enemy_names = [x.strip() for x in enemies_in.split(",") if x.strip()]
        enemy_ids = [champion_name_to_id(n, name_to_id) for n in enemy_names]

        # Recommend steps, avoiding repeats
        picked = []

        s1, why1 = recommend_step(base1, l1_1, l2_1, l3_1, str(patch), role, champ, opp, picked)
        if s1:
            picked.append(s1)

        s2, why2 = recommend_step(base2, l1_2, l2_2, l3_2, str(patch), role, champ, opp, picked)
        if s2:
            picked.append(s2)

        s3, why3 = recommend_step(base3, l1_3, l2_3, l3_3, str(patch), role, champ, opp, picked)
        if s3:
            picked.append(s3)

        # Teamcomp suggestions (lightweight): re-use your heuristic list from teamcomp_counters
        from src.teamcomp_counters import suggest_situational
        situational, reasons = suggest_situational(enemy_ids, champ_tags_map, item_name_map, item_exists)

        champ_print = id_to_name.get(champ, str(champ))
        opp_print = id_to_name.get(opp, str(opp)) if opp else "None"

        print("\n=== BUILD PATH ===")
        print(f"Patch: {patch} | Role: {role} | Champ: {champ_print} | Opp: {opp_print}")

        print("\nPATH (first 3 completed items):")
        for idx, (it, why) in enumerate([(s1, why1), (s2, why2), (s3, why3)], start=1):
            if it is None:
                print(f"- Step {idx}: (no recommendation)")
            else:
                print(f"- Step {idx}: {int(it)} — {item_names.get(int(it), str(it))}  [{why}]")

        print("\nSITUATIONAL (teamcomp):")
        if situational:
            for s in situational:
                print("-", s)
        else:
            print("- No strong teamcomp counters detected.")

        print("\nWHY (teamcomp):")
        for r in reasons:
            print("-", r)

        print("\n")

            # ----- Save result to JSON -----
        import os

        os.makedirs("output", exist_ok=True)

        result = {
            "patch": patch,
            "role": role,
            "champion": champ_print,
            "opponent": opp_print,
            "path": [
                {
                    "step": 1,
                    "item_id": int(s1) if s1 else None,
                    "item_name": item_names.get(int(s1), None) if s1 else None,
                    "reason": why1,
                },
                {
                    "step": 2,
                    "item_id": int(s2) if s2 else None,
                    "item_name": item_names.get(int(s2), None) if s2 else None,
                    "reason": why2,
                },
                {
                    "step": 3,
                    "item_id": int(s3) if s3 else None,
                    "item_name": item_names.get(int(s3), None) if s3 else None,
                    "reason": why3,
                },
            ],
            "situational": situational,
            "teamcomp_reasons": reasons,
        }

        with open("output/last_recommendation.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print("Saved to output/last_recommendation.json")


        again = input("Another? (y/n): ").strip().lower()
        if again != "y":
            break


if __name__ == "__main__":
    main()