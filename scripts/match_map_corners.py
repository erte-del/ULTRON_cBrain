"""Number the corners of every track from its 51GT3 HD map PDF, then snap them to our layout.

    python scripts/match_map_corners.py "<path to the ACC TRACKS folder>"

For each track: read the numbers and the outline from the map (scripts/pdf_map_outline.py),
place each number on the lap, then move it onto the nearest curvature apex of our layout
(within 2% of the lap). Results go into backend/library_tracks/<id>.json as "numbered_corners",
with the status of each track. FastF1 official corners (where we have them) are used to report
the error, not to number the track.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pdf_map_outline as mapper  # noqa: E402

LIB = Path(__file__).resolve().parent.parent / "backend" / "library_tracks"
MAPS = {  # track id -> the HD map (relative to the ACC TRACKS folder)
    "barcelona": "Barcelona-Catalunya/Barcelona-Catalunya.pdf",
    "brands-hatch": "Brands Hatch/Brands Hatch.pdf",
    "cota": "Circuit of the Americas/Circuit of the Americas.pdf",
    "donington": "Donington Park/Donington Park.pdf",
    "hungaroring": "Hungaroring/Hungaroring.pdf",
    "imola": "Imola/Imola.pdf",
    "indianapolis": "Indianapolis/Indianapolis.pdf",
    "kyalami": "Kyalami/Kyalami.pdf",
    "laguna-seca": "Laguna Seca/Laguna Seca.pdf",
    "misano": "Misano/Misano.pdf",
    "monza": "Monza/Monza.pdf",
    "mount-panorama": "Mount Panorama (Bathurst)/Mount Panorama.pdf",
    "nurburgring": "Nürburgring Grand Prix/Nürburgring .pdf",
    "oulton-park": "Oulton Park/Oulton Park.pdf",
    "paul-ricard": "Paul Ricard/Paul Ricard.pdf",
    "red-bull-ring": "Red Bull Ring/Red Bull Ring.pdf",
    "silverstone": "Silverstone/Silverstone.pdf",
    "spa": "Spa-Francorchamps/Circuit de Spa-Francorchamps.pdf",
    "suzuka": "Suzuka/Suzuka.pdf",
    "valencia": "Circuit Ricardo Tormo (Valencia)/Circuit Ricardo Tormo (Valencia).pdf",
    "watkins-glen": "Watkins Glen/Watkins Glen.pdf",
    "zandvoort": "Zandvoort/Zandvoort.pdf",
    "zolder": "Zolder/Zolder.pdf",
}
SNAP = 0.02  # how far (share of the lap) a numbered corner may move to reach our apex


def best_shift(corners: list[dict], apexes: list[dict]) -> float:
    """The START label sits a little off the real start line, which moves every number the same
    amount. Find that shift (within +-0.08 of the lap) by matching the numbers to our apexes."""
    if not apexes or not corners:
        return 0.0

    def cost(d: float) -> float:
        total = 0.0
        for c in corners:
            f = (c["fraction"] + d) % 1
            total += min(min(abs(a["fraction"] - f), 1 - abs(a["fraction"] - f)) for a in apexes)
        return total

    return min((k / 1000 for k in range(-80, 81)), key=cost)


def expected_labels(ref: dict) -> list[tuple[int, str]]:
    """The labels the map should have, in lap order: 1..turns, with sub-corners like 8A after their number."""
    out = []
    for n in range(1, ref["turns"] + 1):
        out.append((n, ""))
        for lt in ref.get("letters", []):
            if lt[:-1] == str(n):
                out.append((n, lt[-1]))
    return out


def repair(corners: list[dict], apexes: list[dict], ref: dict) -> tuple[list[dict], int]:
    """Numbers must rise along the lap. Keep the longest rising run; place the rest (labels read from the
    wrong spot, or missing) in the gaps between kept ones, on the sharpest apexes there."""
    order = expected_labels(ref)
    found = {(c["number"], c["letter"].lower()): c["fraction"] for c in corners}
    keys = [k for k in order if k in found]
    # longest increasing subsequence of fractions in label order
    best = [[k] for k in keys]
    for i, k in enumerate(keys):
        for j in range(i):
            if found[keys[j]] < found[k] and len(best[j]) + 1 > len(best[i]):
                best[i] = best[j] + [k]
    kept = set(max(best, key=len)) if best else set()
    fixed = {k: found[k] for k in kept}
    todo = [k for k in order if k not in kept]
    i = 0
    while i < len(order):
        if order[i] in kept:
            i += 1
            continue
        j = i
        while j < len(order) and order[j] not in kept:
            j += 1
        lo = fixed[order[i - 1]] if i > 0 else 0.0
        hi = fixed[order[j]] if j < len(order) else 1.0
        need = j - i
        inside = [a for a in apexes if lo < a["fraction"] < hi]
        pick = sorted(sorted(inside, key=lambda a: a["radius_m"])[:need], key=lambda a: a["fraction"])
        for k, a in zip(order[i:j], pick):
            fixed[k] = a["fraction"]
        for n_, k in enumerate(order[i + len(pick):j], start=1):  # no apex left in the gap: spread the rest evenly
            fixed[k] = lo + (hi - lo) * (len(pick) + n_) / (need + 1)
        i = j
    out = [dict(number=k[0], letter=k[1], fraction=round(f, 4)) for k, f in fixed.items()]
    return sorted(out, key=lambda c: c["fraction"]), len(todo)


def snap(fraction: float, apexes: list[dict]) -> tuple[float, bool]:
    if not apexes:
        return fraction, False
    best = min(apexes, key=lambda a: min(abs(a["fraction"] - fraction), 1 - abs(a["fraction"] - fraction)))
    gap = min(abs(best["fraction"] - fraction), 1 - abs(best["fraction"] - fraction))
    return (best["fraction"], True) if gap <= SNAP else (fraction, False)


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for tid, rel in MAPS.items():
        track = json.loads((LIB / f"{tid}.json").read_text(encoding="utf-8"))
        ref = json.loads((LIB / "_turn_reference.json").read_text(encoding="utf-8"))["tracks"][tid]
        try:
            found = mapper.map_corners(str(root / rel), ref["turns"] + len(ref.get("letters", [])))
        except ValueError as e:
            print(f"{tid:15} FAILED: {e}")
            continue
        shift = best_shift(found["corners"], track.get("apexes", []))
        found["corners"] = [dict(c, fraction=round((c["fraction"] + shift) % 1, 4)) for c in found["corners"]]
        found["corners"], repaired = repair(found["corners"], track.get("apexes", []), ref)
        official = {c["number"]: c["fraction"] for c in track.get("f1_corners", []) if c["letter"] == ""}
        errs = [abs(c["fraction"] - official[c["number"]]) for c in found["corners"] if c["number"] in official and not c["letter"]]
        track["map_corners_raw"] = found["corners"]  # what the map says, before any decision
        track["map_corners_snapped"] = [dict(c, fraction=round(snap(c["fraction"], track.get("apexes", []))[0], 4))
                                        for c in found["corners"]]
        (LIB / f"{tid}.json").write_text(json.dumps(track, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{tid:15} shift {shift:+.3f}  repaired {repaired:2}  numbers: {len(found['corners'])} (site: {ref['turns']})" + (f"  FastF1 mean err {sum(errs)/len(errs):.3f}" if errs else ""))
