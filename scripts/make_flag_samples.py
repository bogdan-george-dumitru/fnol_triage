"""Dev helper: render handwriting-style FNOL images that trigger AI-predicate flags.

Run with an ephemeral Pillow:
    uv run --with pillow python -m scripts.make_flag_samples

Produces two samples whose narrative (not keywords) should make the model raise an
AI-predicate flag:
  - samples/arson_handwritten_ro.png        -> suspected_arson
  - samples/fraud_theft_handwritten_ro.png  -> suspected_fraud_narrative
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Noteworthy.ttc",
    "/System/Library/Fonts/Chalkboard.ttc",
    "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
    "/System/Library/Fonts/Supplemental/Marker Felt.ttf",
]

ARSON = [
    "Notificare dauna - incendiu",
    "",
    "Polita: PROP-2024-331050",
    "Data: 07.10.2025",
    "",
    "A luat foc casa azi-noapte. Am simtit",
    "un miros puternic de benzina si focul",
    "a pornit in trei locuri deodata.",
    "Pagube mari. Nu sunt raniti.",
    "",
    "Vasile Dumitrescu",
    "tel. 0755 900 123",
]

FRAUD_THEFT = [
    "Notificare dauna - furt",
    "",
    "Polita: PROP-2024-558120",
    "Data: 06.10.2025",
    "",
    "Mi s-au furat bijuterii si ceasuri",
    "scumpe. Nu sunt urme de spargere,",
    "usa era intacta. Nu am facut",
    "plangere la politie.",
    "As vrea plata cat mai repede.",
    "",
    "Maria Ionescu",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size)


def render(lines: list[str], out: Path, seed: int) -> None:
    """Render word by word with jitter so it looks like messy, uneven handwriting."""
    rng = random.Random(seed)
    paper = (247, 245, 238)
    line_h = 66
    w, h = 1010, 90 + line_h * len(lines)
    img = Image.new("RGBA", (w, h), paper + (255,))

    for li, line in enumerate(lines):
        y0 = 48 + li * line_h
        x = 60 + rng.randint(-8, 12)
        for wi, word in enumerate(line.split(" ")):
            if not word:
                x += 20
                continue
            size = 36 + rng.randint(-5, 6)
            font = _load_font(size)
            bbox = font.getbbox(word)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tile = Image.new("RGBA", (tw + 24, th + 24), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            ink = (28 + rng.randint(-12, 12), 36 + rng.randint(-12, 14), 70 + rng.randint(-12, 28))
            # draw twice, 1px apart, for an uneven ink weight
            td.text((12 - bbox[0], 12 - bbox[1]), word, font=font, fill=ink)
            td.text((13 - bbox[0], 12 - bbox[1]), word, font=font, fill=ink)
            tile = tile.rotate(rng.uniform(-6, 6), expand=True, resample=Image.BICUBIC)
            y_jit = int(9 * math.sin(li * 1.3 + wi * 0.8)) + rng.randint(-8, 8)
            img.alpha_composite(tile, (int(x), int(y0 + y_jit)))
            x += tile.width - 18 + rng.randint(-3, 9)

    final = img.convert("RGB").rotate(rng.uniform(-2.2, 2.2), expand=True, fillcolor=paper)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out)
    print(f"Wrote {out} ({final.size[0]}x{final.size[1]})")


def main() -> None:
    render(ARSON, Path("samples/arson_handwritten_ro.png"), seed=11)
    render(FRAUD_THEFT, Path("samples/fraud_theft_handwritten_ro.png"), seed=29)


if __name__ == "__main__":
    main()
