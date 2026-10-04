"""Maakt de achtergrond van het .dmg-venster.

    .venv/bin/python ontwerp/beatcut2/icoon/maak-dmg-achtergrond.py

Levert drie bestanden in deze map:

- `dmg-achtergrond.png`      660x400, wat een gewoon scherm toont
- `dmg-achtergrond@2x.png`   1320x800, de bron voor een retina-scherm
- `dmg-achtergrond.tiff`     allebei in een bestand, en dat is wat de dmg krijgt

Waarom een .tiff: het script van Tauri kopieert de opgegeven achtergrond
onveranderd de schijfkopie in. Twee losse PNG's doet het niets mee. Een
multi-resolutie TIFF (`tiffutil -cathidpicheck`) is het enige bestand waarin
Finder allebei de maten tegelijk ziet.

De plekken van de twee iconen staan in `app/src-tauri/tauri.conf.json` onder
`bundle.macOS.dmg`. Die getallen en de getallen hieronder horen gelijk te
blijven; staan ze uit elkaar, dan zweeft de pijl naast de iconen.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HIER = Path(__file__).resolve().parent

BREED, HOOG = 660, 400
APP = (180, 180)        # = bundle.macOS.dmg.appPosition
PROGRAMMAS = (480, 180)  # = bundle.macOS.dmg.applicationFolderPosition

DONKER = (11, 12, 15)
LICHT_BOVEN = (26, 28, 34)
ACCENT = (184, 230, 60)
TEKST = (232, 234, 237)
GEDEMPT = (138, 143, 152)

FONTS = [
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(punten: int) -> ImageFont.FreeTypeFont:
    for pad in FONTS:
        if Path(pad).exists():
            try:
                return ImageFont.truetype(pad, punten)
            except OSError:
                continue
    raise RuntimeError(f"geen bruikbaar lettertype gevonden in {FONTS}")


def teken(schaal: int) -> Image.Image:
    b, h = BREED * schaal, HOOG * schaal
    img = Image.new("RGB", (b, h), DONKER)
    d = ImageDraw.Draw(img)

    # Zachte verloop van boven naar beneden; geeft diepte zonder af te leiden.
    for y in range(h):
        f = (1 - y / h) ** 2
        d.line(
            [(0, y), (b, y)],
            fill=tuple(int(DONKER[i] + (LICHT_BOVEN[i] - DONKER[i]) * f) for i in range(3)),
        )

    # Pijl van de app naar Programma's, tussen de twee iconen door.
    y = APP[1] * schaal
    x0 = (APP[0] + 95) * schaal
    x1 = (PROGRAMMAS[0] - 95) * schaal
    dik = max(1, round(2.5 * schaal))
    d.line([(x0, y), (x1 - 9 * schaal, y)], fill=ACCENT, width=dik)
    punt = 9 * schaal
    d.polygon(
        [(x1, y), (x1 - punt * 1.6, y - punt * 0.8), (x1 - punt * 1.6, y + punt * 0.8)],
        fill=ACCENT,
    )

    d.text((b // 2, 48 * schaal), "BeatCut", font=_font(28 * schaal),
           fill=TEKST, anchor="mm")
    # 296 en niet lager: Finder tekent de titelbalk en de padbalk over de
    # bovenkant van deze afbeelding heen, dus alles onder ~300 valt buiten
    # beeld. Gemeten op de echte schijfkopie (schermafbeelding, 02-10-2026).
    d.text((b // 2, 296 * schaal), "Sleep BeatCut naar Programma's",
           font=_font(15 * schaal), fill=GEDEMPT, anchor="mm")
    return img


def main() -> None:
    een = HIER / "dmg-achtergrond.png"
    twee = HIER / "dmg-achtergrond@2x.png"
    teken(1).save(een)
    teken(2).save(twee)
    subprocess.run(
        ["tiffutil", "-cathidpicheck", str(een), str(twee),
         "-out", str(HIER / "dmg-achtergrond.tiff")],
        check=True, capture_output=True,
    )
    for p in (een, twee, HIER / "dmg-achtergrond.tiff"):
        print(f"{p.name}: {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
