import json
from pathlib import Path
import pandas as pd

DD_META = Path("data/raw/ddragon/ddragon_meta.json")


# A small, practical set of counter items (IDs are stable-ish but can change across seasons)
# We’ll load item names via Data Dragon so it’s readable.
COUNTER_ITEMS = {
    "anti_heal_ad": [3033],   # Mortal Reminder (example; may vary by season)
    "anti_heal_ap": [3011],   # Chemtech Putrifier removed in some seasons; will filter by availability
    "anti_heal_general": [3123],  # Executioner's Calling (example)
    "anti_tank_ad": [3036],   # Lord Dominik's Regards
    "anti_tank_onhit": [3153],# Blade of the Ruined King
    "mr": [3065, 3156],       # Spirit Visage, Maw of Malmortius
    "armor": [3075, 6333],    # Thornmail, Death's Dance (not pure armor but common)
    "spellshield": [3814],    # Edge of Night
    "tenacity": [3111],       # Mercury's Treads (boots)
}

# Champion “threat” heuristics using Data Dragon tags
# Tags include: Assassin, Fighter, Mage, Marksman, Support, Tank
def enemy_threat_flags(enemy_champ_ids, champ_tags_map):
    tags = []
    for cid in enemy_champ_ids:
        t = champ_tags_map.get(int(cid), [])
        tags.extend(t)

    flags = {
        "many_mages": tags.count("Mage") >= 3,
        "many_ad": (tags.count("Marksman") + tags.count("Fighter") + tags.count("Assassin")) >= 4,
        "many_assassins": tags.count("Assassin") >= 2,
        "many_tanks": tags.count("Tank") >= 2,
    }
    return flags


def load_ddragon_maps():
    meta = json.loads(DD_META.read_text(encoding="utf-8"))
    version = meta["ddragon_version"]

    champ_path = Path(f"data/raw/ddragon/{version}/championFull.json")
    item_path = Path(f"data/raw/ddragon/{version}/item.json")

    champ_json = json.loads(champ_path.read_text(encoding="utf-8"))["data"]
    item_json = json.loads(item_path.read_text(encoding="utf-8"))["data"]

    champ_tags_map = {}
    for _, info in champ_json.items():
        champ_tags_map[int(info["key"])] = info.get("tags", [])

    item_name_map = {}
    for item_id_str, info in item_json.items():
        item_name_map[int(item_id_str)] = info.get("name", item_id_str)

    item_exists = set(item_name_map.keys())
    return champ_tags_map, item_name_map, item_exists


def suggest_situational(enemy_champ_ids, champ_tags_map, item_name_map, item_exists):
    flags = enemy_threat_flags(enemy_champ_ids, champ_tags_map)

    suggestions = []
    reasons = []

    # VERY IMPORTANT: these are heuristics; we only recommend items that exist in current Data Dragon
    def add_items(keys, reason):
        added = []
        for k in keys:
            for item in COUNTER_ITEMS.get(k, []):
                if item in item_exists:
                    added.append(item)
        if added:
            suggestions.extend(added)
            reasons.append(reason)

    if flags["many_mages"]:
        add_items(["mr"], "Enemy comp is mage-heavy → consider MR options.")

    if flags["many_tanks"]:
        add_items(["anti_tank_ad", "anti_tank_onhit"], "Enemy comp has multiple tanks → consider tank-shred items.")

    if flags["many_assassins"]:
        add_items(["spellshield", "armor"], "Enemy has multiple assassins → consider survivability/spell-shield.")

    # de-duplicate while keeping order
    seen = set()
    uniq = []
    for it in suggestions:
        if it not in seen:
            seen.add(it)
            uniq.append(it)

    named = [f"{it}: {item_name_map.get(it, str(it))}" for it in uniq[:5]]
    return named, reasons