"""Maakt de twee afbeeldingen die de Windows-installer (NSIS) toont.

    .venv/bin/python ontwerp/beatcut2/icoon/maak-nsis-beelden.py

- `nsis-header.bmp`   150x57, rechtsboven op elke pagina na de eerste
- `nsis-zijbalk.bmp`  164x314, de hele linkerkant van de welkomstpagina

De maten zijn niet vrij te kiezen: NSIS schaalt niet en toont een afbeelding
van een ander formaat scheef of afgekapt. BMP in 24 bit is het enige formaat
dat MUI2 leest — een PNG hernoemen naar .bmp levert een lege plek op.

De paden staan in `app/src-tauri/tauri.conf.json` onder `bundle.windows.nsis`.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HIER = Path(__file__).resolve().parent

BG = (11, 12, 15)          # --bg
ACCENT = (200, 241, 53)    # --accent
WIT = (243, 244, 246)      # --text


def balkjes(d: ImageDraw.ImageDraw, x: int, y: int, eenheid: float) -> None:
    """Het BeatCut-logo: vijf staafjes, het middelste wit en het hoogst."""
    # (x-offset, hoogte, wit?) in eenheden van 'eenheid', zoals in App.tsx.
    for dx, hoog, wit in ((0, 4, False), (3.5, 10, False), (7, 14, True), (10.5, 8, False), (14, 3, False)):
        links = x + dx * eenheid
        boven = y + (14 - hoog) / 2 * eenheid
        d.rounded_rectangle(
            [links, boven, links + 2 * eenheid, boven + hoog * eenheid],
            radius=max(1, eenheid),
            fill=WIT if wit else ACCENT,
        )


def header() -> Image.Image:
    im = Image.new("RGB", (150, 57), BG)
    d = ImageDraw.Draw(im)
    balkjes(d, 101, 17, 1.6)   # rechts, want links staat de pagina-titel
    return im


def zijbalk() -> Image.Image:
    im = Image.new("RGB", (164, 314), BG)
    d = ImageDraw.Draw(im)
    # Een flauwe gloed in de accentkleur achter het logo.
    for r in range(70, 0, -2):
        mix = r / 70
        d.ellipse(
            [82 - r, 120 - r, 82 + r, 120 + r],
            fill=tuple(round(b + (a - b) * 0.10 * (1 - mix)) for a, b in zip(ACCENT, BG)),
        )
    balkjes(d, 54, 106, 2.0)
    d.line([24, 246, 140, 246], fill=(42, 46, 55))
    return im


def main() -> None:
    for naam, beeld in (("nsis-header.bmp", header()), ("nsis-zijbalk.bmp", zijbalk())):
        pad = HIER / naam
        beeld.save(pad, "BMP")
        print(f"{pad.name}: {beeld.size[0]}x{beeld.size[1]}, {pad.stat().st_size} bytes")


if __name__ == "__main__":
    main()
