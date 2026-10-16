"""Dev helper: render a clean, typed FNOL PDF (with a real text layer).

Run with an ephemeral fpdf2:
    uv run --with fpdf2 python -m scripts.make_sample_pdf

Produces eval/testset/clean_claim_ro.pdf — a typed property claim so the ingest
text-layer path (pypdf) is exercised, as opposed to the handwritten/vision path.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

LINES = [
    ("Notificare dauna - locuinta", 15, True),
    ("", 6, False),
    ("Polita: PROP-2024-331050", 12, False),
    ("Data evenimentului: 27.09.2025", 12, False),
    ("Locatie: Str. Garii 14, Sibiu", 12, False),
    ("Asigurat: Vasile Dumitrescu", 12, False),
    ("", 6, False),
    ("Descriere:", 12, True),
    ("S-a spart un furtun la masina de spalat si s-a inundat bucataria si", 11, False),
    ("holul. Parchetul laminat este deteriorat. Estimam pagubele la 11.000 RON.", 11, False),
    ("Nu sunt raniti.", 11, False),
    ("", 6, False),
    ("Contact: 0755 900 123", 11, False),
]


def main() -> None:
    pdf = FPDF()
    pdf.add_page()
    for text, size, bold in LINES:
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.cell(0, 8, text, ln=True)
    out = Path("eval/testset/clean_claim_ro.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
