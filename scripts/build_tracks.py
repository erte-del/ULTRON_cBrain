"""Build backend/library_tracks/<id>.json: layout + heavy braking zones for every ACC track.

Run once (needs internet; nothing here runs inside Ultron):
    pip install fastf1 numpy matplotlib
    python scripts/build_tracks.py all [--preview DIR]      (or list track ids)

Corner numbers/names are NOT produced: they are added by hand afterwards.
Sources: FastF1 (F1 laps), TUM racetrack-database (Brands Hatch), OpenStreetMap (ODbL, the rest).
Lovely Sim Racing track data (CC BY-NC-SA 4.0) is only used to find the start/finish line,
the direction of travel and the lap length. Zones are ESTIMATES from a simple GT3-like speed model.
"""
import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "library_tracks"
LOVELY = "https://raw.githubusercontent.com/Lovely-Sim-Racing/lovely-track-data/HEAD/data/assettocorsacompetizione/{}.json"
TUM = "https://raw.githubusercontent.com/TUMFTM/racetrack-database/master/tracks/{}.csv"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
DS = 5.0  # metres between layout samples

# layout source: ("f1", year, event) | ("tum", file) | ("osm", lat, lon, half-height in degrees of latitude)
TRACKS = {
    "barcelona": ("f1", 2022, "Spanish Grand Prix"),
    "brands-hatch": ("tum", "BrandsHatch"),
    "cota": ("f1", 2024, "United States Grand Prix"),
    "donington": ("osm", 52.8306, -1.3750, 0.015),
    "hungaroring": ("f1", 2024, "Hungarian Grand Prix"),
    "imola": ("f1", 2024, "Emilia Romagna Grand Prix"),
    "indianapolis": ("osm", 39.7950, -86.2347, 0.015),
    "kyalami": ("osm", -25.9967, 28.0689, 0.015),
    "laguna-seca": ("osm", 36.5842, -121.7536, 0.015),
    "misano": ("osm", 43.9608, 12.6839, 0.015),
    "monza": ("f1", 2024, "Italian Grand Prix"),
    "mount-panorama": ("osm", -33.4440, 149.5610, 0.02, ["Mountain Straight", "Griffins Bend", "Conrod Straight", "The Cutting", "The Esses",
                                                        "Forrest's Elbow", "Reid Park", "Murrays Corner", "Pit Straight", "The Chase",
                                                        "Hell Corner", "Brocks Skyline", "Sulman Park", "McPhillamy Park"]),  # public roads, no raceway tag
    "nurburgring": ("f1", 2020, "Eifel Grand Prix"),
    "nurburgring-24h": ("osm", 50.3356, 6.9475, 0.05),
    "oulton-park": ("osm", 53.1778, -2.6139, 0.015),
    "paul-ricard": ("f1", 2022, "French Grand Prix"),
    "red-bull-ring": ("f1", 2024, "Austrian Grand Prix"),
    "silverstone": ("f1", 2024, "British Grand Prix"),
    "snetterton": ("osm", 52.4637, 0.9456, 0.015),
    "spa": ("f1", 2024, "Belgian Grand Prix"),
    "suzuka": ("f1", 2024, "Japanese Grand Prix"),
    "valencia": ("osm", 39.4883, -0.6314, 0.015),
    "watkins-glen": ("osm", 42.3369, -76.9272, 0.02),
    "zandvoort": ("f1", 2024, "Dutch Grand Prix"),
    "zolder": ("osm", 50.9906, 5.2564, 0.015),
}
# Direction of travel the Lovely corner markers could not settle (margins of 2 m and 5 m): they picked the
# wrong one. The 51GT3 maps fit only the other direction (scripts/check_numbering_geometry.py).
INVERT_DIRECTION = {"brands-hatch", "zolder"}
NOTES = {  # hand-collected guide notes (short, with source)
    "spa": [dict(text="Kemmel Straight into Les Combes is one of the best overtaking spots; heavy braking starts about 100 m before the apex.",
                 source="https://simracingsetup.com/?p=11872633")],
}


def http(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "ultron-track-build/0.2 (personal project)", "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8")


# ---------- geometry ----------
def smooth(a, k):
    if k <= 1:
        return a
    pad = np.r_[a[-k:], a, a[:k]]
    return np.convolve(pad, np.ones(k) / k, mode="same")[k:-k]


def resample(xy):
    p = np.vstack([xy, xy[0]])
    p = p[np.r_[True, np.hypot(*np.diff(p, axis=0).T) > 1e-6]]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    n = int(round(s[-1] / DS))
    si = np.linspace(0, s[-1], n, endpoint=False)
    return np.c_[np.interp(si, s, p[:, 0]), np.interp(si, s, p[:, 1])], s[-1]


def curvature(pts, k):
    """signed curvature 1/m, positive = left turn."""
    sm = np.c_[smooth(pts[:, 0], k), smooth(pts[:, 1], k)]
    d = (np.roll(sm, -1, 0) - np.roll(sm, 1, 0)) / (2 * DS)
    dd = (np.roll(sm, -1, 0) - 2 * sm + np.roll(sm, 1, 0)) / DS**2
    return (d[:, 0] * dd[:, 1] - d[:, 1] * dd[:, 0]) / np.maximum(np.hypot(*d.T), 1e-9) ** 3


def find_peaks(ka, min_curv=1 / 400):
    """curvature peaks = corner apexes (greedy by height, >= 40 m apart)."""
    n = len(ka)
    cand = [i for i in range(n) if ka[i] > min_curv and ka[i] >= ka[i - 1] and ka[i] >= ka[(i + 1) % n]]
    out = []
    for i in sorted(cand, key=lambda q: -ka[q]):
        if all(min((i - j) % n, (j - i) % n) >= 8 for j in out):
            out.append(i)
    return np.array(sorted(out), dtype=int)


# ---------- GT3-like speed model (estimate!) ----------
def speed_profile(kappa):
    k = np.abs(kappa)
    v = np.minimum(np.where(k > 0.0010, np.sqrt(15.0 / np.maximum(k - 0.0010, 1e-9)), 85.0), 85.0)
    n = len(v)
    for _ in range(2):
        for i in range(2 * n - 1, -1, -1):
            i, j = i % n, (i + 1) % n
            v[i] = min(v[i], math.sqrt(v[j] ** 2 + 2 * (13 + 0.0008 * v[j] ** 2) * DS))
    for _ in range(2):
        for i in range(2 * n):
            i, j = i % n, (i + 1) % n
            v[j] = min(v[j], math.sqrt(v[i] ** 2 + 2 * max(9 - 0.0013 * v[i] ** 2, 0) * DS))
    return v


def runs(mask):
    n = len(mask)
    if mask.all() or not mask.any():
        return []
    off = int(np.argmin(mask))
    m = np.roll(mask, -off)
    out, i = [], 0
    while i < n:
        if m[i]:
            j = i
            while j + 1 < n and m[j + 1]:
                j += 1
            out.append(((i + off) % n, (j + off) % n))
            i = j + 1
        else:
            i += 1
    return out


def braking_zones(v, kappa):
    n = len(v)
    zs = []
    for a, b in runs(np.roll(v, -1) < v - 0.02):
        if zs and (a - zs[-1][1]) % n <= 3:
            zs[-1] = (zs[-1][0], b)  # merge zones <= 15 m apart
        else:
            zs.append((a, b))
    res = []
    for a, b in zs:
        b1 = (b + 1) % n
        drop = (v[a] - v[b1]) * 3.6
        if drop < 25:
            continue
        back, i = 0, a
        while back < n and abs(kappa[(i - 1) % n]) < 1 / 500:
            i, back = (i - 1) % n, back + 1
        res.append(dict(a=a, b=b1, v0=v[a] * 3.6, v1=v[b1] * 3.6, drop=drop, straight=back * DS))
    return res


# ---------- layout loaders: (xy metres, F1 brake trace or None, note) ----------
def load_f1(year, event):
    import logging
    import fastf1
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    cache = ROOT / "backend" / "storage" / "f1cache"
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))
    s = fastf1.get_session(year, event, "Q")
    s.load(telemetry=True, weather=False, messages=False)
    tel = s.laps.pick_fastest().get_telemetry()
    rot = math.radians(s.get_circuit_info().rotation)
    R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    xy = np.c_[tel["X"], tel["Y"]] / 10.0 @ R.T
    ci = s.get_circuit_info().corners
    cxy = np.c_[ci["X"], ci["Y"]] / 10.0 @ R.T
    corners = [dict(number=int(r.Number), letter=str(r.Letter or ""), xy=c) for r, c in zip(ci.itertuples(), cxy)]
    return xy, dict(rel=tel["RelativeDistance"].to_numpy(), on=tel["Brake"].to_numpy().astype(bool), corners=corners), f"{year} {event} qualifying fastest lap"


def load_tum(name):
    rows = [list(map(float, l.split(",")))[:2] for l in http(TUM.format(name)).splitlines() if l and not l.startswith("#")]
    return np.array(rows), None, "TUM racetrack-database centre line"


def osm_ways(lat, lon, dlat, names=None):
    dlon = dlat / math.cos(math.radians(lat))
    if names:  # circuit is a public road: take ways by street name from the main OSM API
        js = json.loads(http(f"https://api.openstreetmap.org/api/0.6/map.json?bbox={lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"))
        nodes = {e["id"]: (e["lon"], e["lat"]) for e in js["elements"] if e["type"] == "node"}
        return [dict(tags=w["tags"], nodes=w["nodes"], xy=[nodes[n] for n in w["nodes"]]) for w in js["elements"]
                if w["type"] == "way" and w.get("tags", {}).get("name") in names and w["tags"].get("highway") not in ("footway", "path", "steps")]
    q = f'[out:json][timeout:90];way["highway"="raceway"]({lat-dlat},{lon-dlon},{lat+dlat},{lon+dlon});out geom;'
    for url in OVERPASS:
        try:
            js = json.loads(http(url, urllib.parse.urlencode({"data": q}).encode()))
            return [dict(tags=w.get("tags", {}), nodes=w["nodes"], xy=[(g["lon"], g["lat"]) for g in w["geometry"]])
                    for w in js["elements"] if w["type"] == "way"]
        except Exception:
            continue
    js = json.loads(http(f"https://api.openstreetmap.org/api/0.6/map.json?bbox={lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"))
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in js["elements"] if e["type"] == "node"}
    return [dict(tags=w["tags"], nodes=w["nodes"], xy=[nodes[n] for n in w["nodes"]]) for w in js["elements"]
            if w["type"] == "way" and w.get("tags", {}).get("highway") == "raceway"]


def load_osm(lat, lon, dlat, target, names=None):
    ways = []
    for w in osm_ways(lat, lon, dlat, names):
        t = w["tags"]
        bad = "kart" in t.get("name", "").lower() or "pit lane" in (t.get("name", "") + " " + t.get("service", "")).lower() or "pit_lane" in t.get("service", "") or any(x in t.get("sport", "") for x in ("kart", "drag", "bmx", "cycl", "horse"))
        if not bad:
            ways.append(w)
    if not ways:
        raise RuntimeError("no raceway ways in OpenStreetMap here")
    pos, adj = {}, {}
    for w in ways:
        for nid, c in zip(w["nodes"], w["xy"]):
            pos[nid] = (((c[0] - lon) * 111320 * math.cos(math.radians(lat))), (c[1] - lat) * 110574)
        for a, b in zip(w["nodes"], w["nodes"][1:]):
            adj.setdefault(a, set()).add(b)
            if w["tags"].get("oneway") != "yes":
                adj.setdefault(b, set()).add(a)
    dist = lambda a, b: math.dist(pos[a], pos[b])
    starts = list(dict.fromkeys([n for n, s in adj.items() if len(s) > 2] + [w["nodes"][0] for w in ways]))
    best, limit = [None, None], target * 1.25
    sys.setrecursionlimit(50000)

    def dfs(start, node, path, seen, length):
        for nb in adj.get(node, ()):
            if nb == start and len(path) > 2:
                L = length + dist(node, nb)
                if best[0] is None or abs(L - target) < abs(best[0] - target):
                    best[0], best[1] = L, list(path)
            elif nb not in seen and length + dist(node, nb) < limit:
                seen.add(nb)
                path.append(nb)
                dfs(start, nb, path, seen, length + dist(node, nb))
                path.pop()
                seen.discard(nb)

    for s in starts:
        dfs(s, s, [s], {s}, 0.0)
    if best[1] is None:
        raise RuntimeError("no closed loop found in OpenStreetMap data")
    return np.array([pos[n] for n in best[1]]), None, "OpenStreetMap raceway ways"


# ---------- build ----------
def build(tid):
    lov = json.loads(http(LOVELY.format(tid)))
    src = TRACKS[tid]
    if src[0] == "f1":
        raw, brake, note = load_f1(src[1], src[2])
    elif src[0] == "tum":
        raw, brake, note = load_tum(src[1])
    else:
        raw, brake, note = load_osm(src[1], src[2], src[3], lov["length"], src[4] if len(src) > 4 else None)
    pts0, L = resample(raw)
    n = len(pts0)
    ksm = 9 if src[0] == "f1" else 5
    cap = 150 / (L / n)
    marks = []
    for t in lov["turn"]:
        m = t.get("marker")
        if m is None:
            m = ((t.get("start") or 0) + (t.get("end") or 0)) / 2
        marks.append(m)
    mi = np.array([int(m * n) for m in marks])

    def fit(pts):
        """best start-line shift and mean distance (m) from Lovely corner markers to real curvature peaks."""
        ka = np.abs(smooth(curvature(pts, ksm), 3))
        peaks = find_peaks(ka)
        idx = np.arange(n)
        dpk = np.minimum((peaks[None, :] - idx[:, None]) % n, (idx[:, None] - peaks[None, :]) % n).min(1) if len(peaks) else np.full(n, cap)
        sc = np.minimum(dpk[(mi[:, None] + np.arange(n)[None, :]) % n], cap).sum(0)
        sh = int(np.argmin(sc))
        return sh, sc[sh] * (L / n) / len(mi)

    sh0, err0 = fit(pts0)
    err1 = flip_margin = None
    if src[0] == "f1":  # F1 laps start at the line and run in race direction
        pts = pts0
    else:
        sh1, err1 = fit(pts0[::-1])
        flip = (err1 < err0) != (tid in INVERT_DIRECTION)
        flip_margin = abs(err1 - err0)
        pts = np.roll(pts0[::-1] if flip else pts0, -(sh1 if flip else sh0), 0)
    kappa = curvature(pts, ksm)
    ka = np.abs(smooth(kappa, 3))
    peaks = find_peaks(ka)
    v = speed_profile(kappa)

    # unnumbered corner list (apexes) to help counting corners by hand later
    corners = []
    for p in peaks:
        sp = min(v[(p + d) % n] for d in range(-6, 7)) * 3.6
        if sp < 210:
            corners.append(dict(fraction=round(p / n, 4), direction="left" if kappa[p] > 0 else "right",
                                radius_m=round(1 / abs(kappa[p])), est_min_speed_kmh=round(sp)))
    apexes = []  # every bend with radius < 800 m, flat-out kinks included (used to number corners)
    for p in find_peaks(ka, 1 / 800):
        apexes.append(dict(fraction=round(p / n, 4), direction="left" if kappa[p] > 0 else "right", radius_m=round(1 / abs(kappa[p])),
                           est_min_speed_kmh=round(min(v[(p + d) % n] for d in range(-6, 7)) * 3.6)))
    f1_corners = []
    if brake is not None:
        for c in brake["corners"]:
            f1_corners.append(dict(number=c["number"], letter=c["letter"], fraction=round(int(np.argmin(np.hypot(*(pts - c["xy"]).T))) / n, 4)))
    bz = []
    for z in braking_zones(v, kappa):
        cls = "heavy" if z["drop"] >= 110 else "medium" if z["drop"] >= 60 else "light"
        conf = None
        if brake is not None:
            conf = bool(np.any(brake["on"] & (np.abs(brake["rel"] - z["a"] / n) < 0.02)))
            if not conf:
                cls = "lift"  # F1 cars lift or stay flat here
        cand = cls in ("heavy", "medium") and z["straight"] >= 200 and z["drop"] >= 80
        if cls == "heavy" or cand:
            ap = min(peaks, key=lambda p: (p - z["a"]) % n) if len(peaks) else z["b"]
            bz.append({"start": round(z["a"] / n, 4), "end": round(z["b"] / n, 4), "apex": round(ap / n, 4), "class": cls,
                       "speed_from_kmh": round(z["v0"]), "speed_to_kmh": round(z["v1"]), "straight_before_m": round(z["straight"]),
                       "f1_brake_confirmed": conf, "overtaking_candidate": bool(cand)})
    data = dict(id=tid, name=lov["name"], length_m=lov["length"], layout_source=src[0], layout_note=note,
                sectors=lov.get("sector"), corners=corners, apexes=apexes, f1_corners=f1_corners, braking_zones=bz, notes=NOTES.get(tid, []),
                layout=dict(step_m=round(L / n * 3, 2), points=np.round(pts[::3] - pts.mean(0), 1).tolist(), start_finish=0),
                corner_numbers="not added yet",
                estimate_warning="Corner speeds and braking/overtaking zones are estimates from a simple GT3-like model on the layout, not recorded GT3 data.",
                attribution="Layout: " + {"f1": "F1 timing data via FastF1", "tum": "TUM racetrack-database (LGPL-3.0)",
                                          "osm": "OpenStreetMap contributors (ODbL)"}[src[0]] + ". Start line/direction aided by Lovely Sim Racing track data (CC BY-NC-SA 4.0).")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{tid}.json").write_text(json.dumps(data, indent=1, default=lambda o: o.item()), encoding="utf-8")
    info = dict(len_ratio=round(L / lov["length"], 3), anchor_err_m=round(err0 if err1 is None else min(err0, err1)),
                dir_margin_m=None if flip_margin is None else round(flip_margin), corners=len(corners),
                heavy=sum(z["class"] == "heavy" for z in bz), overtaking=sum(z["overtaking_candidate"] for z in bz))
    return data, dict(pts=pts, v=v, n=n, zones=bz), info


def draw(ax, data, g, small=False):
    pts, v, n = g["pts"], g["v"], g["n"]
    ax.scatter(pts[:, 0], pts[:, 1], c=v * 3.6, s=2 if small else 6, cmap="viridis")
    for z in g["zones"]:
        idx = [(int(z["start"] * n) + i) % n for i in range((int(z["end"] * n) - int(z["start"] * n)) % n + 1)]
        ax.plot(pts[idx, 0], pts[idx, 1], color="red" if z["class"] == "heavy" else "orange", lw=2 if small else 5, alpha=.85)
        if z["overtaking_candidate"]:
            ax.scatter(*pts[idx[0]], marker="*", s=40 if small else 260, color="lime", edgecolor="black", zorder=5)
    ax.plot(*pts[0], "ws", mec="k", ms=4 if small else 10)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(data["name"], fontsize=7 if small else 10)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks", nargs="+")
    ap.add_argument("--preview")
    a = ap.parse_args()
    ids = list(TRACKS) if a.tracks == ["all"] else a.tracks
    done = []
    for t in ids:
        try:
            data, g, info = build(t)
        except Exception as e:  # keep going; report at the end
            print(f"FAILED {t}: {type(e).__name__}: {e}", flush=True)
            continue
        print(t, info, flush=True)
        done.append((data, g))
    if a.preview and done:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        Path(a.preview).mkdir(parents=True, exist_ok=True)
        for data, g in done:
            fig, ax = plt.subplots(figsize=(9, 7))
            draw(ax, data, g)
            fig.savefig(Path(a.preview) / f"{data['id']}.png", dpi=100, bbox_inches="tight")
            plt.close(fig)
        cols = 5
        rows = math.ceil(len(done) / cols)
        fig, axs = plt.subplots(rows, cols, figsize=(cols * 3.4, rows * 3))
        for ax in np.ravel(axs):
            ax.axis("off")
        for ax, (data, g) in zip(np.ravel(axs), done):
            draw(ax, data, g, small=True)
        fig.savefig(Path(a.preview) / "sheet.png", dpi=110, bbox_inches="tight")
