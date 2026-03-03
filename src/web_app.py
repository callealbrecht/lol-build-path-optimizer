import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional, List

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


# ==============================
# CONFIG
# ==============================

APP_DATA = Path("app_data")

BUILD_STEPS_PATH = APP_DATA / "build_steps.csv"
CHAMPION_PATH = APP_DATA / "championFull.json"
ITEM_PATH = APP_DATA / "item.json"

MIN_GAMES_L1 = 20
MIN_GAMES_L2 = 35
MIN_GAMES_L3 = 60
ALPHA = 0.9


# ==============================
# FastAPI setup
# ==============================

app = FastAPI(title="LoL Build Path Recommender (Emerald+)")
templates = Jinja2Templates(directory="templates")

MODELS = {}


# ==============================
# Utilities
# ==============================

def normalize(s: str) -> str:
    return "".join(c.lower() for c in s if c.isalnum())


def load_champion_maps():
    data = json.loads(CHAMPION_PATH.read_text(encoding="utf-8"))["data"]

    name_to_id = {}
    id_to_name = {}

    for champ in data.values():
        cid = int(champ["key"])
        name = champ["name"]
        id_to_name[cid] = name

        name_to_id[normalize(name)] = cid
        name_to_id[normalize(champ["id"])] = cid

    return name_to_id, id_to_name


def load_item_names():
    data = json.loads(ITEM_PATH.read_text(encoding="utf-8"))["data"]
    return {int(k): v["name"] for k, v in data.items()}


def champion_name_to_id(name: str, name_to_id):
    key = normalize(name)
    if key in name_to_id:
        return name_to_id[key]
    raise ValueError(f"Unknown champion: {name}")


# ==============================
# Model building
# ==============================

def baseline_for_step(df, step_col):
    base = {}
    grouped = df.dropna(subset=[step_col]).groupby(["patch", "role", "championId"])

    for key, grp in grouped:
        counter = Counter(int(x) for x in grp[step_col])
        base[key] = [it for it, _ in counter.most_common(10)]

    return base


def matchup_tables_for_step(df, step_col):
    def build(keys):
        table = {}
        grouped = df.dropna(subset=[step_col, "opponentChampionId"]).groupby(keys)

        for key, grp in grouped:
            games = len(grp)
            base_wr = grp["win"].mean()

            item_games = defaultdict(int)
            item_wins = defaultdict(int)

            for _, r in grp.iterrows():
                it = int(r[step_col])
                item_games[it] += 1
                item_wins[it] += int(r["win"])

            item_wr = {it: (g, item_wins[it] / g) for it, g in item_games.items()}
            table[key] = {"games": games, "base_wr": base_wr, "item_wr": item_wr}

        return table

    return (
        build(["patch", "role", "championId", "opponentChampionId"]),
        build(["role", "championId", "opponentChampionId"]),
        build(["championId", "opponentChampionId"]),
    )


def rerank(candidates, stats, min_games):
    scored = []
    base_wr = stats["base_wr"]

    for it in candidates:
        if it not in stats["item_wr"]:
            scored.append((0.0, it))
            continue

        g_with, wr_with = stats["item_wr"][it]
        delta = wr_with - base_wr
        confidence = min(1.0, g_with / (min_games * 2))
        score = ALPHA * delta * confidence
        scored.append((score, it))

    scored.sort(reverse=True)
    return [it for _, it in scored]


def recommend_step(base, l1, l2, l3, patch, role, champ, opp, picked):
    base_key = (patch, role, champ)
    candidates = base.get(base_key, [])
    candidates = [c for c in candidates if c not in picked]

    if not candidates:
        return None, "No baseline data."

    if opp is None:
        return candidates[0], "Baseline (no opponent)."

    key1 = (patch, role, champ, opp)
    if key1 in l1 and l1[key1]["games"] >= MIN_GAMES_L1:
        ranked = rerank(candidates, l1[key1], MIN_GAMES_L1)
        return ranked[0], f"L1 matchup (n={l1[key1]['games']})"

    key2 = (role, champ, opp)
    if key2 in l2 and l2[key2]["games"] >= MIN_GAMES_L2:
        ranked = rerank(candidates, l2[key2], MIN_GAMES_L2)
        return ranked[0], f"L2 matchup (n={l2[key2]['games']})"

    key3 = (champ, opp)
    if key3 in l3 and l3[key3]["games"] >= MIN_GAMES_L3:
        ranked = rerank(candidates, l3[key3], MIN_GAMES_L3)
        return ranked[0], f"L3 matchup (n={l3[key3]['games']})"

    return candidates[0], "Baseline fallback."


# ==============================
# Startup (build model once)
# ==============================

@app.on_event("startup")
def startup():
    df = pd.read_csv(BUILD_STEPS_PATH)
    df["patch"] = df["patch"].astype(str)

    item_names = load_item_names()
    name_to_id, id_to_name = load_champion_maps()

    base1 = baseline_for_step(df, "step1")
    base2 = baseline_for_step(df, "step2")
    base3 = baseline_for_step(df, "step3")

    l1_1, l2_1, l3_1 = matchup_tables_for_step(df, "step1")
    l1_2, l2_2, l3_2 = matchup_tables_for_step(df, "step2")
    l1_3, l2_3, l3_3 = matchup_tables_for_step(df, "step3")

    MODELS.update(
        dict(
            df=df,
            item_names=item_names,
            name_to_id=name_to_id,
            id_to_name=id_to_name,
            base1=base1, base2=base2, base3=base3,
            l1_1=l1_1, l2_1=l2_1, l3_1=l3_1,
            l1_2=l1_2, l2_2=l2_2, l3_2=l3_2,
            l1_3=l1_3, l2_3=l2_3, l3_3=l3_3,
            default_patch=str(df["patch"].mode().iloc[0]),
            champ_names=sorted(id_to_name.values())
        )
    )


# ==============================
# Routes
# ==============================

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_patch": MODELS["default_patch"],
            "champ_names": MODELS["champ_names"],
        },
    )


@app.post("/api/recommend")
async def api_recommend(request: Request):
    data = await request.json()

    patch = str(data.get("patch") or MODELS["default_patch"])
    role = str(data.get("role")).upper()

    champ = champion_name_to_id(data.get("champion"), MODELS["name_to_id"])
    opp_name = data.get("opponent")
    opp = champion_name_to_id(opp_name, MODELS["name_to_id"]) if opp_name else None

    picked = []

    s1, w1 = recommend_step(MODELS["base1"], MODELS["l1_1"], MODELS["l2_1"], MODELS["l3_1"], patch, role, champ, opp, picked)
    if s1: picked.append(s1)

    s2, w2 = recommend_step(MODELS["base2"], MODELS["l1_2"], MODELS["l2_2"], MODELS["l3_2"], patch, role, champ, opp, picked)
    if s2: picked.append(s2)

    s3, w3 = recommend_step(MODELS["base3"], MODELS["l1_3"], MODELS["l2_3"], MODELS["l3_3"], patch, role, champ, opp, picked)

    return {
        "patch": patch,
        "role": role,
        "champion": MODELS["id_to_name"][champ],
        "opponent": MODELS["id_to_name"].get(opp) if opp else None,
        "path": [
            {"step": 1, "item": MODELS["item_names"].get(s1), "reason": w1},
            {"step": 2, "item": MODELS["item_names"].get(s2), "reason": w2},
            {"step": 3, "item": MODELS["item_names"].get(s3), "reason": w3},
        ]
    }