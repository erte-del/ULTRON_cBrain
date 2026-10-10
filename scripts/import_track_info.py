"""Copy the 51GT3 info text files into the project and pull the key facts out of them.

    python scripts/import_track_info.py "<path to the ACC TRACKS folder>"

Writes backend/library_tracks/info/<id>.txt (git-ignored: it is 51GT3's text, for personal use)
and backend/library_tracks/_facts.json (length, turns, elevation, country, location, other names).
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "backend" / "library_tracks"

# folder name in the ACC TRACKS folder -> track id
FOLDERS = {
    "Barcelona-Catalunya": "barcelona", "Brands Hatch": "brands-hatch", "Circuit of the Americas": "cota",
    "Donington Park": "donington", "Hungaroring": "hungaroring", "Imola": "imola", "Indianapolis": "indianapolis",
    "Kyalami": "kyalami", "Laguna Seca": "laguna-seca", "Misano": "misano", "Monza": "monza",
    "Mount Panorama (Bathurst)": "mount-panorama", "Nürburgring (includes the Nordschleife)": "nurburgring-24h",
    "Nürburgring Grand Prix": "nurburgring", "Oulton Park": "oulton-park", "Paul Ricard": "paul-ricard",
    "Red Bull Ring": "red-bull-ring", "Silverstone": "silverstone", "Snetterton": "snetterton",
    "Spa-Francorchamps": "spa", "Suzuka": "suzuka", "Circuit Ricardo Tormo (Valencia)": "valencia",
    "Watkins Glen": "watkins-glen", "Zandvoort": "zandvoort", "Zolder": "zolder",
}
KEYS = {"FIA Grade": "grade", "Circuit Length": "length", "Track Elevation Change": "elevation", "Number of Turns": "turns",
        "Continent": "continent", "Country / Region": "country", "State / Province": "region", "Location": "location",
        "English Name": "english_name", "Also Known As": "also_known_as"}
# Extra ways people say a track's name.
EXTRA_ALIASES = {
    "mount-panorama": ["bathurst", "the mountain", "mount panorama"],
    "nurburgring-24h": ["nordschleife", "24h", "24 hours", "the ring", "green hell", "nurburgring 24h", "nurburgring nordschleife"],
    "nurburgring": ["nurburgring gp", "nurburgring grand prix", "nurburg"],
    "cota": ["austin", "circuit of the americas"],
    "indianapolis": ["indy", "ims"],
    "valencia": ["ricardo tormo", "cheste"],
    "red-bull-ring": ["spielberg", "a1 ring", "osterreichring"],
    "paul-ricard": ["le castellet", "ricard"],
    "watkins-glen": ["the glen", "watkins"],
    "spa": ["spa francorchamps", "francorchamps"],
    "barcelona": ["catalunya", "montmelo", "circuit de barcelona catalunya"],
    "laguna-seca": ["laguna", "weathertech raceway"],
    "imola": ["enzo e dino ferrari"],
    "zandvoort": ["zandvoort gp"],
    "brands-hatch": ["brands"],
    "donington": ["donington park"],
    "oulton-park": ["oulton"],
    "silverstone": ["silverstone circuit"],
    "hungaroring": ["hungary", "budapest"],
}


def clean(value: str) -> str:
    value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value)  # [Europe](https://...) -> Europe
    value = re.sub(r"\(→[^)]*\)", "", value)
    return value.strip(" *").strip()


def parse(text: str) -> dict:
    facts: dict = {}
    for line in text.splitlines():
        m = re.match(r"^\s*\*?\s*([A-Za-z/ ]+?)\s*:\s*(.+)$", line)
        if m and m[1].strip() in KEYS:
            facts[KEYS[m[1].strip()]] = clean(m[2])
    return facts


if __name__ == "__main__":
    root = Path(sys.argv[1])
    (OUT / "info").mkdir(parents=True, exist_ok=True)
    out: dict = {}
    for folder, tid in FOLDERS.items():
        files = list((root / folder).glob("info*.txt"))
        text = files[0].read_text(encoding="utf-8") if files else ""
        (OUT / "info" / f"{tid}.txt").write_text(text, encoding="utf-8")
        facts = parse(text)
        names = [tid.replace("-", " ")] + EXTRA_ALIASES.get(tid, []) + [facts.get("english_name", "")]
        names += [n.strip() for n in facts.get("also_known_as", "").split(",")]
        out[tid] = dict(facts=facts, aliases=sorted({n for n in names if n}))
        print(f"{tid:16} facts={len(facts)} text={len(text)} chars")
    (OUT / "_facts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
