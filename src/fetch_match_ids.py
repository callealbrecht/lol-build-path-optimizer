import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY")

ROUTING_REGION = "europe"  # EUW uses 'europe' for match-v5
QUEUE_ID = 420             # Ranked Solo
COUNT_PER_PLAYER = 50      # start small
MAX_PLAYERS = 200          # start small

HEADERS = {"X-Riot-Token": API_KEY}


def riot_get(url: str, params: dict | None = None):
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else 5
            print(f"429 rate limit. Sleeping {sleep_s}s...")
            time.sleep(sleep_s)
            continue

        if r.status_code >= 400:
            try:
                print("HTTP error payload:", r.json())
            except Exception:
                print("HTTP error text:", r.text[:500])
            r.raise_for_status()

        return r.json()


def main():
    if not API_KEY:
        raise RuntimeError("RIOT_API_KEY missing in .env")

    puuids_path = "data/raw/emerald_plus_puuids.csv"
    df = pd.read_csv(puuids_path)

    # Shuffle so you don't always hit the same early pages of the ladder
    df = df.sample(n=min(MAX_PLAYERS, len(df)), random_state=42)

    seen = set()
    rows = []

    for i, row in enumerate(df.itertuples(index=False), start=1):
        puuid = row.puuid
        url = f"https://{ROUTING_REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"queue": QUEUE_ID, "start": 0, "count": COUNT_PER_PLAYER}

        match_ids = riot_get(url, params=params)
        print(f"[{i}/{len(df)}] got {len(match_ids)} match ids")

        for mid in match_ids:
            if mid in seen:
                continue
            seen.add(mid)
            rows.append({"matchId": mid})

        time.sleep(0.8)  # gentle pacing

    out = pd.DataFrame(rows).drop_duplicates()
    os.makedirs("data/raw", exist_ok=True)
    out_path = "data/raw/match_ids.csv"
    out.to_csv(out_path, index=False)
    print(f"\nSaved {len(out)} unique match IDs to {out_path}")


if __name__ == "__main__":
    main()