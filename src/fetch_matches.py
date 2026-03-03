import os
import time
import json
import random
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY")

ROUTING_REGION = "europe"   # EUW match-v5 routing
HEADERS = {"X-Riot-Token": API_KEY}

IN_PATH = Path("data/raw/match_ids.csv")
OUT_PATH = Path("data/raw/matches.jsonl")

MAX_MATCHES = 5000   # start smaller; you can increase later
SLEEP_S = 0.6       # pacing


def riot_get(url: str, max_net_retries: int = 8):
    """
    Robust GET:
    - retries on 429 with Retry-After
    - retries on transient network errors/timeouts
    - uses connect+read timeout tuple so it won't hang forever
    """
    net_tries = 0

    while True:
        try:
            r = requests.get(url, headers=HEADERS, timeout=(5, 30))  # (connect, read)

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.SSLError) as e:
            net_tries += 1
            if net_tries > max_net_retries:
                raise RuntimeError(f"Network error after {max_net_retries} retries: {e}") from e
            sleep_s = min(2 ** net_tries, 30) + random.uniform(0, 1)
            print(f"Network error ({type(e).__name__}). Retry {net_tries}/{max_net_retries} in {sleep_s:.1f}s...")
            time.sleep(sleep_s)
            continue

        # Rate limit handling
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else 5
            print(f"429 rate limit. Sleeping {sleep_s}s...")
            time.sleep(sleep_s)
            continue

        # Other HTTP errors
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

    match_ids = pd.read_csv(IN_PATH)["matchId"].tolist()
    match_ids = match_ids[: min(MAX_MATCHES, len(match_ids))]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Resume: skip already downloaded matches
    done = set()
    if OUT_PATH.exists():
        with OUT_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    done.add(obj.get("metadata", {}).get("matchId"))
                except Exception:
                    pass
        print(f"Resuming: found {len(done)} existing matches in {OUT_PATH}")

    written = 0
    with OUT_PATH.open("a", encoding="utf-8") as out:
        for i, mid in enumerate(match_ids, start=1):
            if mid in done:
                continue

            url = f"https://{ROUTING_REGION}.api.riotgames.com/lol/match/v5/matches/{mid}"
            match = riot_get(url)

            out.write(json.dumps(match) + "\n")
            written += 1

            if i % 25 == 0:
                print(f"Processed {i}/{len(match_ids)} (written {written})")

            time.sleep(SLEEP_S)

    print(f"\nDone. Wrote {written} matches to {OUT_PATH}")


if __name__ == "__main__":
    main()