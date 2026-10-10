"""Decide the numbered corners of every track file (backend/library_tracks/<id>.json).

    python scripts/number_corners.py

Rules (run after scripts/match_map_corners.py):
1. F1 tracks with FastF1 official corners whose count equals the 51GT3 turn count: use FastF1's
   official numbers and positions (exact).
2. Other tracks whose 51GT3 map gives exactly the official turn count: use the map numbers,
   snapped to our apexes. Not checked against an official source.
3. Anything else: no numbers, and the status says why. These need a manual pass.
Snetterton (only the short configuration is numbered) and the Nordschleife are skipped on purpose.
"""
import json
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "backend" / "library_tracks"
REF = json.loads((LIB / "_turn_reference.json").read_text(encoding="utf-8"))["tracks"]
SKIP = {"snetterton": "short 3.2 km configuration only; the 300 is not raced",
        "nurburgring-24h": "named corners on the map, not numbered"}


def decide(track: dict, turns: int) -> tuple[list[dict], str]:
    tid = track["id"]
    official = [c for c in track.get("f1_corners", []) if track["layout_source"] == "f1"]
    if official and len(official) == turns:
        out = [dict(number=c["number"], letter=c["letter"], fraction=c["fraction"], source="FastF1 official")
               for c in sorted(official, key=lambda c: c["fraction"])]
        return out, f"official: {len(out)} corners from FastF1"
    mapped = track.get("map_corners_snapped", [])
    if mapped and len(mapped) == turns:
        out = [dict(number=c["number"], letter=c["letter"], fraction=c["fraction"], source="51GT3 map")
               for c in sorted(mapped, key=lambda c: c["fraction"])]
        chk = track.get("numbering_check")
        how = (f"cross-checked against the map outline (fit {chk['outline_fit_pct']}% of track size, {chk['agree']}/{chk['total']} "
               f"numbers within 2% of the lap, worst {chk['worst']:.3f})") if chk else "positions not checked against an official source"
        weak = bool(chk and (chk["outline_fit_pct"] > 4 or chk["agree"] < chk["total"] * 0.7))
        return out, f"from the 51GT3 map: {len(out)} corners, {how}" + (" - weaker match, treat positions as approximate" if weak else "")
    if official:
        why = f"FastF1 has {len(official)} corners, the site says {turns}"
    elif mapped:
        why = f"the map gives {len(mapped)} numbers, the site says {turns}"
    else:
        why = "no numbered map could be read"
    return [], f"not numbered yet: {why}"


def describe(corners: list[dict], apexes: list[dict]) -> None:
    """Copy direction, radius and slowest speed from the nearest apex (within 2% of the lap)."""
    for c in corners:
        if not apexes:
            break
        best = min(apexes, key=lambda a: min(abs(a["fraction"] - c["fraction"]), 1 - abs(a["fraction"] - c["fraction"])))
        if min(abs(best["fraction"] - c["fraction"]), 1 - abs(best["fraction"] - c["fraction"])) <= 0.02:
            c.update(direction=best["direction"], radius_m=best["radius_m"], est_min_speed_kmh=best["est_min_speed_kmh"])


if __name__ == "__main__":
    for path in sorted(LIB.glob("*.json")):
        if path.name.startswith("_"):
            continue
        track = json.loads(path.read_text(encoding="utf-8"))
        tid = track["id"]
        if tid in SKIP:
            track["numbered_corners"], track["numbering_status"] = [], f"not numbered: {SKIP[tid]}"
        else:
            track["numbered_corners"], track["numbering_status"] = decide(track, REF[tid]["turns"] + len(REF[tid].get("letters", [])))
        describe(track["numbered_corners"], track.get("apexes", []))
        path.write_text(json.dumps(track, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{tid:15} {len(track['numbered_corners']):3}  {track['numbering_status']}")
