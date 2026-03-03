import json
import os
from pathlib import Path

import pandas as pd


IN_PATH = Path("data/raw/matches.jsonl")
OUT_PATH = Path("data/processed/participants.parquet")  # requires pyarrow
OUT_CSV = Path("data/processed/participants.csv")       # fallback


def game_version_to_patch(game_version: str) -> str:
    # e.g. "14.17.601.1234" -> "14.17"
    parts = (game_version or "").split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return game_version or ""


def main():
    rows = []

    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            match = json.loads(line)
            metadata = match.get("metadata", {})
            info = match.get("info", {})

            match_id = metadata.get("matchId")
            game_version = info.get("gameVersion", "")
            patch = game_version_to_patch(game_version)

            participants = info.get("participants", [])
            if not participants:
                continue

            # Build lookup by (teamId, teamPosition) to find lane opponent
            by_team_role = {}
            for p in participants:
                team_id = p.get("teamId")
                role = p.get("teamPosition")  # TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY or ""
                if team_id is None or not role:
                    continue
                by_team_role[(team_id, role)] = p

            # Team comps
            team1 = [p.get("championId") for p in participants if p.get("teamId") == 100]
            team2 = [p.get("championId") for p in participants if p.get("teamId") == 200]

            for p in participants:
                team_id = p.get("teamId")
                role = p.get("teamPosition") or ""
                champ = p.get("championId")
                win = int(bool(p.get("win")))

                # Opponent: other team, same teamPosition
                opp_team_id = 200 if team_id == 100 else 100
                opp = by_team_role.get((opp_team_id, role))
                opp_champ = opp.get("championId") if opp else None

                # Choose ally/enemy list based on team
                allies = team1 if team_id == 100 else team2
                enemies = team2 if team_id == 100 else team1

                rows.append({
                    "matchId": match_id,
                    "patch": patch,
                    "teamId": team_id,
                    "puuid": p.get("puuid"),
                    "role": role,
                    "championId": champ,
                    "opponentChampionId": opp_champ,
                    "win": win,
                    "item0": p.get("item0"),
                    "item1": p.get("item1"),
                    "item2": p.get("item2"),
                    "item3": p.get("item3"),
                    "item4": p.get("item4"),
                    "item5": p.get("item5"),
                    "allies": allies,
                    "enemies": enemies,
                })

    df = pd.DataFrame(rows)

    # Keep only “real” roles to reduce noise
    df = df[df["role"].isin(["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"])].copy()

    os.makedirs("data/processed", exist_ok=True)

    # Try parquet first; if pyarrow not installed, write CSV
    try:
        df.to_parquet(OUT_PATH, index=False)
        print(f"Saved {len(df)} rows to {OUT_PATH}")
    except Exception as e:
        df.to_csv(OUT_CSV, index=False)
        print(f"Could not write parquet ({e}). Saved {len(df)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()