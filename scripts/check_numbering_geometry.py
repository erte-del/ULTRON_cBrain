"""Cross-check the corner numbers a second way: by shape.

    python scripts/check_numbering_geometry.py "<path to the ACC TRACKS folder>"

For each track: line up the 51GT3 map outline with our layout (rotate, scale, move; mirror if
needed), place every number on our layout from where its label sits on the map, and compare that
with the position the numbering used (distance along the lap). Prints how well the two outlines
line up and how many numbers agree within 2% of the lap.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match_map_corners as mm  # noqa: E402
import pdf_map_outline as mapper  # noqa: E402

LIB = mm.LIB


def similarity(P: np.ndarray, Q: np.ndarray, reflect: bool):
    """Best scale/rotation/shift taking P onto Q (optionally mirroring P first). Returns (apply, rms)."""
    flip = np.array([1.0, -1.0]) if reflect else np.array([1.0, 1.0])
    pc, qc = (P * flip).mean(0), Q.mean(0)
    A, B = P * flip - pc, Q - qc
    U, S, Vt = np.linalg.svd(A.T @ B)
    if np.linalg.det(U @ Vt) < 0:  # keep it a proper rotation (mirroring is handled by `reflect`)
        U[:, -1] *= -1
        S[-1] *= -1
    R = U @ Vt
    scale = S.sum() / (A**2).sum()

    def apply(X: np.ndarray) -> np.ndarray:
        return (X * flip - pc) @ R * scale + qc

    rms = float(np.sqrt(((apply(P) - Q) ** 2).sum(1).mean()))
    return apply, rms


if __name__ == "__main__":
    root = Path(sys.argv[1])
    ref_all = json.loads((LIB / "_turn_reference.json").read_text(encoding="utf-8"))["tracks"]
    for tid, rel in mm.MAPS.items():
        track = json.loads((LIB / f"{tid}.json").read_text(encoding="utf-8"))
        ref = ref_all[tid]
        try:
            found = mapper.map_corners(str(root / rel), ref["turns"] + len(ref.get("letters", [])))
        except ValueError:
            print(f"{tid:15} map outline not readable")
            continue
        shift = mm.best_shift(found["corners"], track.get("apexes", []))
        ours = np.array(track["layout"]["points"])
        n = len(ours)
        M = len(found["outline"])
        P = np.array(found["outline"])
        Q = np.array([ours[int(((i / M + shift) % 1) * n) % n] for i in range(M)])
        best = min((similarity(P, Q, r) for r in (False, True)), key=lambda t: t[1])
        apply, rms = best
        size = math.hypot(*(ours.max(0) - ours.min(0)))
        agree = total = 0
        worst = 0.0
        for c in found["corners"]:
            xy = found["label_xy"].get((c["number"], c["letter"]))
            if xy is None:
                continue
            q = apply(np.array([xy]))[0]
            frac_geo = int(np.argmin(np.hypot(*(ours - q).T))) / n
            f_arc = (c["fraction"] + shift) % 1
            d = min(abs(frac_geo - f_arc), 1 - abs(frac_geo - f_arc))
            total += 1
            agree += d <= 0.02
            worst = max(worst, d)
        print(f"{tid:15} outline fit {100 * rms / size:4.1f}% of track size | {agree}/{total} numbers agree within 2% | worst {worst:.3f}")
        track["numbering_check"] = dict(outline_fit_pct=round(100 * rms / size, 1), agree=int(agree), total=int(total), worst=round(worst, 3))
        (LIB / f"{tid}.json").write_text(json.dumps(track, indent=1, ensure_ascii=False), encoding="utf-8")
