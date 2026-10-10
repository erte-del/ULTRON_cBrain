"""Read the track outline and corner labels from a 51GT3 HD map PDF (vector data, no OCR).

Returns the thick black track stroke as one polyline (PDF page coordinates) and the
numbers printed on the map with their positions.
"""
import math
import re

from pypdf import PdfReader
from pypdf.generic import ContentStream


def _mul(a, b):  # matrix a then b (PDF convention: [a b c d e f])
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def track_strokes(pdf_path: str, width: float | None = None) -> list[list[tuple[float, float]]]:
    """Every black stroked path with the track's line width (the thickest black one, unless `width` is given)."""
    page = PdfReader(pdf_path).pages[0]
    ops = ContentStream(page.get_contents(), page.pdf).operations
    stack, ctm = [], [1, 0, 0, 1, 0, 0]
    gray_black = (0, 0, 0)
    lw = 1.0
    path: list[list[tuple[float, float]]] = []
    cur = None
    strokes: list[list[tuple[float, float]]] = []
    filled: list[list[tuple[float, float]]] = []
    for operands, op in ops:
        op = op.decode() if isinstance(op, bytes) else op
        a = [float(x) for x in operands if isinstance(x, (int, float)) or type(x).__name__ in ("FloatObject", "NumberObject")]
        if op == "q":
            stack.append((list(ctm), lw, gray_black))
        elif op == "Q" and stack:
            ctm, lw, gray_black = stack.pop()
        elif op == "cm":
            ctm = _mul(a, ctm)
        elif op == "w":
            lw = a[0]
        elif op == "RG":
            gray_black = tuple(a)
        elif op == "m":
            cur = _apply(ctm, a[0], a[1])
            path.append([cur])
        elif op == "l" and cur is not None:
            cur = _apply(ctm, a[0], a[1])
            path[-1].append(cur)
        elif op in ("c", "v", "y") and cur is not None:
            if op == "c":
                p1, p2, p3 = (_apply(ctm, a[0], a[1]), _apply(ctm, a[2], a[3]), _apply(ctm, a[4], a[5]))
            elif op == "v":
                p1, p2, p3 = cur, _apply(ctm, a[0], a[1]), _apply(ctm, a[2], a[3])
            else:
                p1, p2, p3 = _apply(ctm, a[0], a[1]), _apply(ctm, a[2], a[3]), _apply(ctm, a[2], a[3])
            p0 = cur
            for k in range(1, 9):  # sample the bezier curve
                t = k / 8
                x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t * t * p2[0] + t**3 * p3[0]
                y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t * t * p2[1] + t**3 * p3[1]
                path[-1].append((x, y))
            cur = p3
        elif op in ("S", "s"):
            black = len(gray_black) in (1, 3) and max(gray_black) < 0.3
            if black and lw >= 12:
                strokes.append((lw, [p for p in path if len(p) > 1]))
            path = []
            cur = None
        elif op in ("f", "F", "f*", "B"):
            filled.extend(p for p in path if len(p) > 20)  # drawn as a filled shape instead of a line
            path = []
            cur = None
        elif op == "n":
            path = []
            cur = None
    if not strokes:
        if filled:  # the track is a filled band: its outer edge is the biggest outline on the page
            area = lambda p: (max(x for x, _ in p) - min(x for x, _ in p)) * (max(y for _, y in p) - min(y for _, y in p))
            return [max(filled, key=area)]
        return []
    if width is None:  # the track is drawn in the widest black line
        width = max(w for w, _ in strokes)
    return [p for w, ps in strokes if abs(w - width) < 0.5 for p in ps]


def join_outline(strokes, gap: float = 60.0) -> list[tuple[float, float]]:
    """Chain the stroked pieces into one loop by nearest endpoints."""
    pieces = [list(p) for p in strokes]
    if not pieces:
        return []
    loop = pieces.pop(0)
    while pieces:
        best = None
        for i, p in enumerate(pieces):
            for rev in (False, True):
                q = p[::-1] if rev else p
                d = math.dist(loop[-1], q[0])
                if best is None or d < best[0]:
                    best = (d, i, q)
        d, i, q = best
        if d > gap:
            break  # not one loop; keep what we joined
        loop += q[1:]
        pieces.pop(i)
    return loop


def labels(pdf_path: str) -> list[tuple[str, float, float]]:
    """(text, x, y) of every text run on the map, in page coordinates."""
    page = PdfReader(pdf_path).pages[0]
    out = []

    def visit(text, cm, tm, font_dict, font_size):
        t = text.strip()
        if t:
            out.append((t, float(tm[4]), float(tm[5])))

    page.extract_text(visitor_text=visit)
    return out


def numbers(pdf_path: str, turns: int | None = None) -> list[tuple[int, str, float, float]]:
    """Corner labels: (number, letter, x, y).

    Labels printed touching each other come out as one run ('89', '1011'). With the official
    turn count, a run is split into consecutive numbers when the whole number is too big or
    already used. Runs that share a spot ('12 13') are kept together by position.
    """
    found: list[tuple[int, str, float, float]] = []
    seen: set[int] = set()
    for text, x, y in labels(pdf_path):
        if not re.fullmatch(r"\s*\d+[A-Za-z]?(\s+\d+[A-Za-z]?)*\s*", text):
            continue  # titles, START, PIT IN...
        for tok in re.findall(r"\d+[A-Za-z]?", text):
            letter = re.sub(r"\d", "", tok)
            digits = tok[: len(tok) - len(letter)]
            if not digits:
                continue
            whole = int(digits)
            if letter or turns is None or (whole <= turns and whole not in seen and len(digits) <= 2):
                parts = [(whole, letter)]
            else:
                parts = _split_run(digits, turns, seen)
            for n, lt in parts:
                found.append((n, lt, x, y))
                seen.add(n)
    return found


def _split_run(digits: str, turns: int, seen: set[int]) -> list[tuple[int, str]]:
    """'1011' -> [(10, ''), (11, '')]: the split into consecutive numbers that fits the turn count best."""
    best: list[int] | None = None

    def walk(rest: str, acc: list[int]):
        nonlocal best
        if not rest:
            if best is None or len(acc) > len(best):
                best = acc
            return
        for k in range(1, min(3, len(rest)) + 1):
            n = int(rest[:k])
            if n <= turns and n not in seen and (not acc or n == acc[-1] + 1):
                walk(rest[k:], acc + [n])

    walk(digits, [])
    if best is None:
        return [(int(digits), "")]
    return [(n, "") for n in best]





def _densify(loop, step: float = 2.0):
    """Points every `step` pt along the closed loop (straight segments are sparse in the file)."""
    out = []
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        k = max(1, int(math.dist(a, b) / step))
        out += [(a[0] + (b[0] - a[0]) * t / k, a[1] + (b[1] - a[1]) * t / k) for t in range(k)]
    return out


def map_corners(pdf_path: str, turns: int | None = None) -> dict:
    """Numbered corners placed along the outline: {'length_pt', 'corners': [{number, letter, fraction}], 'reversed'}.

    fraction = share of the lap from the START marker, in race direction. Labels that share a
    position (e.g. '12 13') are split by the sharpest turns nearby.
    """
    loop = _densify(join_outline(track_strokes(pdf_path)))
    if len(loop) < 10:
        raise ValueError(f"no track outline found in {pdf_path}")
    n = len(loop)
    seg = [math.dist(loop[i], loop[(i + 1) % n]) for i in range(n)]
    arc = [0.0]
    for s_ in seg[:-1]:
        arc.append(arc[-1] + s_)
    L = arc[-1] + seg[-1]

    def nearest(x, y):
        return min(range(n), key=lambda i: math.dist(loop[i], (x, y)))

    def turn(i):  # turning angle at outline point i
        a, b, c = loop[(i - 4) % n], loop[i], loop[(i + 4) % n]
        h1, h2 = math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(c[1] - b[1], c[0] - b[0])
        return abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)

    start = [(x, y) for t, x, y in labels(pdf_path) if t.upper().startswith("START")]
    s0 = arc[nearest(*start[0])] if start else 0.0

    nums = [(k, lt, x, y) for k, lt, x, y in numbers(pdf_path, turns) if math.dist(loop[nearest(x, y)], (x, y)) < 200]
    groups: dict[tuple[int, int], list] = {}
    for item in nums:
        groups.setdefault((round(item[2]), round(item[3])), []).append(item)

    def frac(a, s):
        return ((a - s) % L) / L

    singles = [(g[0][0], g[0][1], arc[nearest(g[0][2], g[0][3])]) for g in groups.values() if len(g) == 1]
    # race direction: the numbers must rise along the loop from the START marker
    pts = sorted(singles, key=lambda p: frac(p[2], s0))
    up = sum(1 for a, b in zip(pts, pts[1:]) if b[0] > a[0])
    down = sum(1 for a, b in zip(pts, pts[1:]) if b[0] < a[0])
    reversed_ = down > up
    if reversed_:
        loop = loop[::-1]
        arc = [0.0]
        seg = [math.dist(loop[i], loop[(i + 1) % n]) for i in range(n)]
        for s_ in seg[:-1]:
            arc.append(arc[-1] + s_)
        s0 = (L - s0) % L
    placed = [(k, lt, arc[nearest(x, y)]) for g in groups.values() if len(g) == 1 for k, lt, x, y in g]
    for group in groups.values():
        if len(group) == 1:
            continue
        # labels sharing a spot: the sharpest turns within 110 pt of it, one per label, in race order
        bx, by = group[0][2], group[0][3]
        near = [i for i in range(n) if math.dist(loop[i], (bx, by)) <= 110]
        picked = []
        for i in sorted(near, key=lambda i: -(turn(i) - math.dist(loop[i], (bx, by)) / 400)):
            if all(min((i - j) % n, (j - i) % n) > 40 for j in picked):
                picked.append(i)
            if len(picked) == len(group):
                break
        picked = sorted(picked, key=lambda i: arc[i])
        for j, (k, lt, x, y) in enumerate(sorted(group)):
            placed.append((k, lt, arc[picked[j]] if j < len(picked) else arc[nearest(x, y)]))
    corners = sorted(({"number": k, "letter": lt, "fraction": round(frac(a, s0), 4)} for k, lt, a in placed),
                     key=lambda c: c["fraction"])
    # the outline itself, sampled at equal shares of the lap from the start marker (to align it with our layout)
    import bisect
    outline = []
    for i in range(240):
        a = (s0 + L * i / 240) % L
        outline.append(loop[min(bisect.bisect_left(arc, a), n - 1)])
    labels_xy = {(k, lt): (x, y) for g in groups.values() for k, lt, x, y in g}
    return {"length_pt": L, "corners": corners, "reversed": reversed_, "outline": outline, "label_xy": labels_xy}
