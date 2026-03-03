import json
import re
from pathlib import Path

DD_META = Path("data/raw/ddragon/ddragon_meta.json")


def _norm(s: str) -> str:
    # normalize for matching: lower, remove non-letters/numbers
    return re.sub(r"[^a-z0-9]+", "", s.lower().strip())


def load_champion_maps():
    """Returns (name_to_id, id_to_name). Accepts lots of name formats."""
    meta = json.loads(DD_META.read_text(encoding="utf-8"))
    version = meta["ddragon_version"]
    champ_path = Path(f"data/raw/ddragon/{version}/championFull.json")
    champ_json = json.loads(champ_path.read_text(encoding="utf-8"))["data"]

    name_to_id: dict[str, int] = {}
    id_to_name: dict[int, str] = {}

    for _, info in champ_json.items():
        cid = int(info["key"])          # numeric championId used in match data
        name = info["name"]             # e.g., "Lee Sin"
        title = info.get("title", "")   # not used, but could be

        id_to_name[cid] = name

        # Add several keys that users might type
        keys = {
            _norm(name),                # "leesin"
            _norm(info["id"]),          # "leesin" (DDragon internal id)
        }
        for k in keys:
            name_to_id[k] = cid

    # A few common aliases people type (add more whenever you notice them)
    aliases = {
        "wukong": "monkeyking",   # DDragon internal id for Wukong is MonkeyKing
    }
    for user_key, ddragon_key in aliases.items():
        nk = _norm(user_key)
        dk = _norm(ddragon_key)
        if dk in name_to_id:
            name_to_id[nk] = name_to_id[dk]

    return name_to_id, id_to_name


def champion_name_to_id(user_input: str, name_to_id: dict[str, int]) -> int:
    key = _norm(user_input)
    if key in name_to_id:
        return name_to_id[key]

    # helpful error: show closest “starts with” options
    suggestions = [k for k in name_to_id.keys() if k.startswith(key[:4])]
    suggestions = suggestions[:10]
    raise ValueError(f"Unknown champion '{user_input}'. Try a different spelling.")