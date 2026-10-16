"""Dev helper: render a handwriting-style FNOL image to test the vision branch.

Not part of the app or its dependencies. Run with an ephemeral Pillow:
    uv run --with pillow python -m scripts.make_sample_image

Produces samples/handwritten_property_ro.png — a short Romanian property loss note
in a handwriting font, lightly rotated to mimic a phone photo of a paper form.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Candidate handwriting fonts on macOS; falls back to the default bitmap font.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Noteworthy.ttc",
    "/System/Library/Fonts/Chalkboard.ttc",
    "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
    "/System/Library/Fonts/Supplemental/Marker Felt.ttf",
]

LINES = [
    "Notificare dauna - locuinta",
    "",
    "Polita: PROP-2024-778310",
    "Data: 08.10.2025",
    "",
    "In timpul furtunii de azi-noapte a cazut",
    "un copac peste acoperisul casei. Sunt",
    "sparte mai multe tigle si o fereastra de",
    "la mansarda. Nu sunt raniti.",
    "",
    "Ion Petre",
    "tel. 0745 112 334",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size)


def main() -> None:
    w, h = 900, 760
    img = Image.new("RGB", (w, h), (247, 245, 238))  # off-white, paper-ish
    draw = ImageDraw.Draw(img)
    font = _load_font(34)

    y = 48
    for line in LINES:
        draw.text((60, y), line, fill=(28, 36, 64), font=font)
        y += 56

    img = img.rotate(-1.6, expand=True, fillcolor=(247, 245, 238))  # slight skew

    out = Path("samples/handwritten_property_ro.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"Wrote {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
