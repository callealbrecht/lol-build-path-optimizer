import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("RIOT_API_KEY")
REGION = "euw1"  # change if needed
BASE_URL = f"https://{REGION}.api.riotgames.com"
HEADERS = {"X-Riot-Token": API_KEY}


def riot_get(url: str, params: dict | None = None):
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else 5
            print(f"Rate limited (429). Sleeping {sleep_s}s...")
            time.sleep(sleep_s)
            continue

        if r.status_code >= 400:
            try:
                print("HTTP error payload:", r.json())
            except Exception:
                print("HTTP error text:", r.text[:500])
            r.raise_for_status()

        return r.json()


def get_tier_entries(tier: str, division: str):
    url = f"{BASE_URL}/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{division}"
    page = 1
    all_entries = []

    while True:
        data = riot_get(url, params={"page": page})

        if isinstance(data, dict):
            raise RuntimeError(f"Unexpected response (dict) for {tier} {division} page {page}: {data}")

        if not data:
            break

        if "puuid" not in data[0]:
            raise RuntimeError(f"Missing puuid in response for {tier} {division} page {page}: {data[0]}")

        all_entries.extend(data)
        print(f"{tier} {division} page {page} fetched ({len(data)} players)")
        page += 1
        time.sleep(1)

    return all_entries


def main():
    if not API_KEY:
        raise RuntimeError("RIOT_API_KEY not found. Put it in .env as RIOT_API_KEY=RGAPI-...")

    tiers = {
        "EMERALD": ["I", "II", "III", "IV"],
        "DIAMOND": ["I", "II", "III", "IV"],
    }

    rows = []
    for tier, divisions in tiers.items():
        for division in divisions:
            entries = get_tier_entries(tier, division)
            for p in entries:
                puuid = p.get("puuid")
                if not puuid:
                    continue
                rows.append({
                    "puuid": puuid,
                    "tier": tier,
                    "division": division,
                    "lp": p.get("leaguePoints"),
                    "wins": p.get("wins"),
                    "losses": p.get("losses"),
                })

    df = pd.DataFrame(rows).drop_duplicates(subset=["puuid"])
    os.makedirs("data/raw", exist_ok=True)
    out_path = "data/raw/emerald_plus_puuids.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} unique players to {out_path}")


if __name__ == "__main__":
    main()