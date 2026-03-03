import pandas as pd
from collections import Counter, defaultdict


DATA_PATH = "data/processed/participants.csv"

TOPN_BASELINE = 8          # consider top baseline items
MIN_MATCHUP_GAMES = 25     # only trust matchup deltas if enough games
ALPHA = 0.60               # how strongly matchup affects score (0..1)


def load_data():
    df = pd.read_csv(DATA_PATH)

    # Replace 0 with None (empty item slots)
    for i in range(6):
        df[f"item{i}"] = df[f"item{i}"].replace(0, None)

    # Keep only real roles
    df = df[df["role"].isin(["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"])].copy()
    return df


def compute_baseline_items(df):
    """
    Baseline: top items by frequency for each (patch, role, championId)
    """
    baseline = {}

    grouped = df.groupby(["patch", "role", "championId"])
    for key, group in grouped:
        c = Counter()
        for _, row in group.iterrows():
            items = [row[f"item{i}"] for i in range(6)]
            c.update([x for x in items if pd.notna(x)])
        baseline[key] = [item for item, _ in c.most_common(TOPN_BASELINE)]

    return baseline


def compute_matchup_item_stats(df):
    """
    For each matchup (patch, role, champ, oppChamp), compute:
      - total games
      - winrate overall
      - winrate when item is present
    Returns dict keyed by (patch, role, champ, oppChamp) -> dict with:
      {"games": int, "base_wr": float, "item_wr": {itemId: (games_with_item, wr_with_item)}}
    """
    matchup_stats = {}

    # Create a column with item sets for quick counting
    item_cols = [f"item{i}" for i in range(6)]

    grouped = df.groupby(["patch", "role", "championId", "opponentChampionId"])
    for key, group in grouped:
        games = len(group)
        if games == 0:
            continue
        base_wr = group["win"].mean()

        # Count per item
        item_games = defaultdict(int)
        item_wins = defaultdict(int)

        for _, row in group.iterrows():
            win = int(row["win"])
            for it in [row[c] for c in item_cols]:
                if pd.isna(it):
                    continue
                item_games[it] += 1
                item_wins[it] += win

        item_wr = {}
        for it, g in item_games.items():
            item_wr[it] = (g, item_wins[it] / g)

        matchup_stats[key] = {"games": games, "base_wr": base_wr, "item_wr": item_wr}

    return matchup_stats


def recommend_items(baseline, matchup_stats, patch, role, champ, opp):
    base_key = (patch, role, champ)
    if base_key not in baseline:
        return [], ["No baseline data for this champ/role/patch."]

    candidates = baseline[base_key]

    explanations = []
    scored = []

    mkey = (patch, role, champ, opp)
    m = matchup_stats.get(mkey)

    if not m or m["games"] < MIN_MATCHUP_GAMES:
        return candidates[:5], [f"Not enough matchup data vs opponent (need {MIN_MATCHUP_GAMES}+ games)."]

    base_wr = m["base_wr"]

    for it in candidates:
        it_stats = m["item_wr"].get(it)
        if not it_stats:
            # No data for this item in this matchup; keep neutral
            score = 0.0
            scored.append((score, it))
            continue

        g_with, wr_with = it_stats
        delta = wr_with - base_wr

        # Weighted score: prefer items with more games and better delta
        confidence = min(1.0, g_with / (MIN_MATCHUP_GAMES * 2))
        score = ALPHA * delta * confidence

        scored.append((score, it))

        if abs(delta) >= 0.03 and g_with >= MIN_MATCHUP_GAMES:  # only explain meaningful deltas
            direction = "better" if delta > 0 else "worse"
            explanations.append(
                f"Item {int(it)} is {direction} vs opponent in this matchup "
                f"(ΔWR {delta:+.1%} over {g_with} games)."
            )

    scored.sort(reverse=True, key=lambda x: x[0])
    ranked = [it for _, it in scored]

    if not explanations:
        explanations = [f"Used matchup re-ranking based on Emerald+ games (n={m['games']})."]

    return ranked[:5], explanations[:4]


def main():
    df = load_data()
    print(f"Loaded {len(df)} rows")

    baseline = compute_baseline_items(df)
    print("Baseline computed.")

    matchup_stats = compute_matchup_item_stats(df)
    print("Matchup stats computed.")

    # Demo using a random real row
    sample = df.sample(1, random_state=1).iloc[0]
    patch = sample["patch"]
    role = sample["role"]
    champ = int(sample["championId"])
    opp = int(sample["opponentChampionId"]) if pd.notna(sample["opponentChampionId"]) else None

    rec, why = recommend_items(baseline, matchup_stats, patch, role, champ, opp)
    print("\nDemo Input:")
    print(f"patch={patch}, role={role}, champ={champ}, opp={opp}")

    print("\nRecommended items (IDs):")
    print(rec)

    print("\nWhy:")
    for line in why:
        print("-", line)


if __name__ == "__main__":
    main()