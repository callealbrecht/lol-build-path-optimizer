import json
import pandas as pd
from champions import load_champion_maps, champion_name_to_id

from recommend_cli import (
    load_df,
    baseline_items,
    build_matchup_tables,
    recommend,
    load_item_names,
)
from teamcomp_counters import load_ddragon_maps, suggest_situational


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


def parse_int_list(s: str):
    # accepts "64,107,99" or "[64, 107, 99]"
    s = s.strip()
    if s.startswith("["):
        return [int(x) for x in json.loads(s)]
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main():
    print("Loading data + building tables (this can take ~10-30s)...")
    item_names = load_item_names()
    champ_tags_map, item_name_map, item_exists = load_ddragon_maps()
    name_to_id, id_to_name = load_champion_maps()

    df = load_df()
    base = baseline_items(df)
    l1, l2, l3 = build_matchup_tables(df)
    print("Ready.\n")

    while True:
        patch = input("Patch (e.g. 15.6) or ENTER for most common in dataset: ").strip()
        if not patch:
            patch = str(df["patch"].mode().iloc[0])

        role_in = input("Role (top/jg/mid/adc/sup): ").strip().lower()
        role = ROLE_MAP.get(role_in)
        if not role:
            print("Unknown role. Try again.\n")
            continue

        champ_name = input("Your champion (e.g. Rengar): ").strip()
        champ = champion_name_to_id(champ_name, name_to_id)

        opp_name = input("Lane opponent (or ENTER to skip): ").strip()
        opp_id = champion_name_to_id(opp_name, name_to_id) if opp_name else None

        enemies_in = input("Enemy team champs (5 names, comma-separated) e.g. Lee Sin,Yasuo,Lux,Nautilus,Aatrox: ").strip()
        enemy_names = [x.strip() for x in enemies_in.split(",") if x.strip()]
        enemy_ids = [champion_name_to_id(n, name_to_id) for n in enemy_names]

        core_ids, why = recommend(df, base, l1, l2, l3, str(patch), role, champ, opp_id)

        situational, reasons = suggest_situational(enemy_ids, champ_tags_map, item_name_map, item_exists)

        print("\n=== RESULTS ===")
        champ_print = id_to_name.get(champ, str(champ))
        opp_print = id_to_name.get(opp_id, str(opp_id)) if opp_id else "None"
        print(f"Patch: {patch} | Role: {role} | Champ: {champ_print} | Opp: {opp_print}")
        print("\nCORE (baseline/matchup):")
        for it in core_ids:
            print(f"- {int(it)}: {item_names.get(int(it), str(it))}")

        print("\nSITUATIONAL (teamcomp):")
        if situational:
            for s in situational:
                print("-", s)
        else:
            print("- No strong teamcomp counters detected.")

        print("\nWHY:")
        for w in why:
            print("-", w)
        for r in reasons:
            print("-", r)

        print("\n")
        again = input("Another? (y/n): ").strip().lower()
        if again != "y":
            break


if __name__ == "__main__":
    main()

