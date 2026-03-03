import os
import time
import json
import random
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY")

ROUTING_REGION = "europe"  # EUW match-v5 routing region
HEADERS = {"X-Riot-Token": API_KEY}

MATCHES_PATH = Path("data/raw/matches.jsonl")       # match details you already downloaded
OUT_PATH = Path("data/raw/timelines.jsonl")         # will be created/appended

MAX_TIMELINES = 1500   # start here; raise later (e.g., 5000)
SLEEP_S = 0.6          # pacing


def riot_get(url: str, max_net_retries: int = 8):
    """Robust GET: retries on 429 + transient network/SSL/timeouts."""
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


def load_match_ids_from_matches_jsonl(path: Path):
    """Read matchIds from matches.jsonl (deduped, stable order)."""
    match_ids = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                mid = obj.get("metadata", {}).get("matchId")
                if mid:
                    match_ids.append(mid)
            except Exception:
                continue

    seen = set()
    uniq = []
    for mid in match_ids:
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(mid)
    return uniq


def main():
    if not API_KEY:
        raise RuntimeError("RIOT_API_KEY missing in .env")

    if not MATCHES_PATH.exists():
        raise FileNotFoundError(
            "Missing data/raw/matches.jsonl. Run your match fetcher first (fetch_matches.py)."
        )

    match_ids = load_match_ids_from_matches_jsonl(MATCHES_PATH)
    match_ids = match_ids[: min(MAX_TIMELINES, len(match_ids))]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Resume support: skip already-downloaded timelines
    done = set()
    if OUT_PATH.exists():
        with OUT_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    done.add(obj.get("metadata", {}).get("matchId"))
                except Exception:
                    pass
        print(f"Resuming: found {len(done)} timelines already in {OUT_PATH}")

    written = 0
    with OUT_PATH.open("a", encoding="utf-8") as out:
        for i, mid in enumerate(match_ids, start=1):
            if mid in done:
                continue

            url = f"https://{ROUTING_REGION}.api.riotgames.com/lol/match/v5/matches/{mid}/timeline"
            tl = riot_get(url)
            out.write(json.dumps(tl) + "\n")
            written += 1

            if i % 25 == 0:
                print(f"Processed {i}/{len(match_ids)} (written {written})")

            time.sleep(SLEEP_S)

    print(f"\nDone. Wrote {written} timelines to {OUT_PATH}")


if __name__ == "__main__":
    main()