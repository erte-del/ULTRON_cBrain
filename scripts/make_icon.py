"""Draw the Ultron icon (the glowing purple orb from the page header) as a macOS iconset.

    python scripts/make_icon.py <folder.iconset>

make_app.sh turns the iconset into applet.icns with `iconutil`.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BACKGROUND = (8, 5, 15)
ORB_LIGHT, ORB_MID, ORB_DARK = (233, 213, 255), (168, 85, 247), (59, 20, 110)


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw(size: int) -> Image.Image:
    s = 1024  # draw big, then shrink for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # macOS-style rounded square
    ImageDraw.Draw(img).rounded_rectangle([40, 40, s - 40, s - 40], radius=200, fill=BACKGROUND)

    # soft glow behind the orb
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([232, 232, s - 232, s - 232], fill=(*ORB_MID, 170))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

    # the orb: a radial gradient with its highlight up and to the left
    orb = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    px = orb.load()
    cx = cy = s / 2
    r = 250
    hx, hy = cx - r * 0.3, cy - r * 0.3
    for y in range(int(cy - r), int(cy + r) + 1):
        for x in range(int(cx - r), int(cx + r) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                t = min(math.hypot(x - hx, y - hy) / (r * 1.4), 1)
                color = mix(ORB_LIGHT, ORB_MID, t / 0.6) if t < 0.6 else mix(ORB_MID, ORB_DARK, (t - 0.6) / 0.4)
                px[x, y] = (*color, 255)
    img.alpha_composite(orb)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        draw(base).save(out / f"icon_{base}x{base}.png")
        draw(base * 2).save(out / f"icon_{base}x{base}@2x.png")


if __name__ == "__main__":
    main()
