"""Bouw een dubbelklikbare BeatCut-app.

    python installer/maak_app.py            # voor dit besturingssysteem
    python installer/maak_app.py --alles    # ook de Windows-starter

Wat het oplevert:

    macOS    installer/uit/BeatCut.app   - in de Dock te slepen, eigen ikoon
    Windows  installer/uit/BeatCut.cmd   - snelkoppeling naar het bureaublad

De app start de engine en opent de browser. Geen server die blijft draaien
als je hem sluit: sluit je het venster van de app, dan stopt de engine ook.

**Dit is nog niet de installer uit `PLAN.md` §9.4.** Die vriest Python in met
PyInstaller en pakt alles in een Tauri-schil met automatische updates. Daar is
Rust voor nodig, en die staat hier niet. Zie `installer/LEESMIJ.md` voor het
verschil en de weg daarheen.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

WORTEL = Path(__file__).resolve().parents[1]
UIT = Path(__file__).resolve().parent / "uit"
NAAM = "BeatCut"
BUNDEL_ID = "nl.koen.beatcut"

# De versie komt van één plek, net als in de engine.
sys.path.insert(0, str(WORTEL / "engine"))
try:
    from cve import __version__ as VERSIE
except Exception:  # noqa: BLE001
    VERSIE = "0.0.0"


# --------------------------------------------------------------------------
# Ikoon
# --------------------------------------------------------------------------


def _ikoon_png(grootte: int) -> bytes:
    """Teken het ikoon: een afgerond blauw vierkant met een afspeeldriehoek.

    Met numpy en opencv, want die zitten al in de venv. Geen extra
    afhankelijkheid voor één plaatje.
    """
    import cv2
    import numpy as np

    g = grootte
    beeld = np.zeros((g, g, 4), dtype=np.uint8)

    # Afgerond vierkant met een verloop van licht naar donker blauw.
    straal = int(g * 0.225)
    masker = np.zeros((g, g), dtype=np.uint8)
    marge = int(g * 0.06)
    cv2.rectangle(masker, (marge + straal, marge), (g - marge - straal, g - marge), 255, -1)
    cv2.rectangle(masker, (marge, marge + straal), (g - marge, g - marge - straal), 255, -1)
    for cx, cy in ((marge + straal, marge + straal), (g - marge - straal, marge + straal),
                   (marge + straal, g - marge - straal), (g - marge - straal, g - marge - straal)):
        cv2.circle(masker, (cx, cy), straal, 255, -1)

    boven = np.array([255, 145, 40], dtype=np.float32)   # BGR: helder blauw
    onder = np.array([200, 90, 0], dtype=np.float32)
    for y in range(g):
        t = y / max(1, g - 1)
        beeld[y, :, :3] = (boven * (1 - t) + onder * t).astype(np.uint8)
    beeld[:, :, 3] = masker

    # Afspeeldriehoek in het midden.
    h = g * 0.30
    b = h * 0.86
    mx, my = g / 2 + g * 0.02, g / 2
    driehoek = np.array([[mx - b / 2, my - h / 2], [mx - b / 2, my + h / 2],
                         [mx + b / 2, my]], dtype=np.int32)
    cv2.fillPoly(beeld, [driehoek], (255, 255, 255, 255), lineType=cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", beeld)
    if not ok:
        raise RuntimeError("ikoon tekenen mislukt")
    return buf.tobytes()


def _icns(doel: Path) -> Path | None:
    """Zet de PNG's om in een .icns. Alleen op macOS; `iconutil` hoort erbij."""
    if sys.platform != "darwin":
        return None
    setmap = doel.parent / f"{NAAM}.iconset"
    if setmap.exists():
        shutil.rmtree(setmap)
    setmap.mkdir(parents=True)
    for grootte in (16, 32, 128, 256, 512):
        (setmap / f"icon_{grootte}x{grootte}.png").write_bytes(_ikoon_png(grootte))
        (setmap / f"icon_{grootte}x{grootte}@2x.png").write_bytes(_ikoon_png(grootte * 2))
    r = subprocess.run(["iconutil", "-c", "icns", str(setmap), "-o", str(doel)],
                       capture_output=True, text=True)
    shutil.rmtree(setmap, ignore_errors=True)
    if r.returncode != 0:
        print("  ikoon overgeslagen:", (r.stderr or "").strip()[:120])
        return None
    return doel


# --------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------

# Twee smaken starter. De ingevroren engine zit in de app zelf en heeft geen
# Python nodig; de bronversie gebruikt de venv naast de broncode. De eerste is
# wat je uitdeelt, de tweede wat je tijdens het bouwen gebruikt.
STARTER_INGEVROREN = """#!/bin/bash
# BeatCut — start de engine en open de browser.
#
# De app is een schil om de lokale server. Bewust geen eigen venstertje: de
# Studio draait in je browser, en die speelt video af zoals het hoort.
set -e
HIER="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HIER/../Resources/engine/beatcut-engine"

if [ ! -x "$ENGINE" ]; then
  osascript -e 'display alert "BeatCut is beschadigd" message "De engine ontbreekt in de app. Installeer BeatCut opnieuw." as critical'
  exit 1
fi

# Draait er al een? Dan alleen het venster openen.
if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:8420/"; then
  open "http://127.0.0.1:8420/"
  exit 0
fi

exec "$ENGINE" studio
"""

STARTER_BRON = """#!/bin/bash
# BeatCut — start de engine uit de broncode (voor tijdens het bouwen).
set -e
WORTEL="{wortel}"
CVE="$WORTEL/.venv/bin/cve"

if [ ! -x "$CVE" ]; then
  osascript -e 'display alert "BeatCut kan de engine niet vinden" message "De map met de engine is verplaatst of de installatie is niet af." as critical'
  exit 1
fi

if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:8420/"; then
  open "http://127.0.0.1:8420/"
  exit 0
fi

cd "$WORTEL"
exec "$CVE" studio
"""


def maak_macos(*, ingevroren: bool = True) -> Path:
    app = UIT / f"{NAAM}.app"
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)

    engine = UIT / "beatcut-engine"
    gebruik_ingevroren = ingevroren and engine.exists()
    if gebruik_ingevroren:
        # In de app, niet ernaast: zo is één map slepen genoeg om te
        # installeren en kan er niets losraken.
        shutil.copytree(engine, res / "engine")
        starter_tekst = STARTER_INGEVROREN
    else:
        starter_tekst = STARTER_BRON.format(wortel=WORTEL)

    starter = macos / NAAM
    starter.write_text(starter_tekst, encoding="utf-8")
    starter.chmod(starter.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    heeft_ikoon = _icns(res / f"{NAAM}.icns") is not None

    plist = {
        "CFBundleName": NAAM,
        "CFBundleDisplayName": f"{NAAM} Video Editor",
        "CFBundleIdentifier": BUNDEL_ID,
        "CFBundleVersion": VERSIE,
        "CFBundleShortVersionString": VERSIE,
        "CFBundleExecutable": NAAM,
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "12.0",
        # Geen menubalk-app: hij opent de browser en verdwijnt naar de
        # achtergrond. `LSUIElement` zou hem helemaal verbergen, en dan kun
        # je hem ook niet meer stoppen.
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.video",
    }
    if heeft_ikoon:
        plist["CFBundleIconFile"] = f"{NAAM}.icns"
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    return app


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

CMD = """@echo off
rem BeatCut - start de engine en open de browser.
title BeatCut Video Editor
set WORTEL={wortel}
set CVE=%WORTEL%\\.venv\\Scripts\\cve.exe

if not exist "%CVE%" (
  echo BeatCut kan de engine niet vinden op %CVE%.
  echo Is de map verplaatst, of is de installatie niet af?
  pause
  exit /b 1
)

cd /d "%WORTEL%"
"%CVE%" studio
"""


def maak_windows() -> Path:
    doel = UIT / f"{NAAM}.cmd"
    doel.write_text(CMD.format(wortel=WORTEL), encoding="utf-8")
    return doel


# --------------------------------------------------------------------------


def maak_dmg(app: Path) -> Path | None:
    """Een schijfkopie met de app en een snelkoppeling naar Programma's.

    Dat is hoe een Mac-gebruiker een app verwacht te krijgen: openen, naar
    Programma's slepen, klaar. `hdiutil` hoort bij macOS, dus geen extra
    gereedschap nodig.
    """
    if sys.platform != "darwin":
        return None
    werk = UIT / "dmg"
    if werk.exists():
        shutil.rmtree(werk)
    werk.mkdir(parents=True)
    shutil.copytree(app, werk / app.name, symlinks=True)
    os.symlink("/Applications", werk / "Programma's")

    doel = UIT / f"{NAAM}-{VERSIE}.dmg"
    doel.unlink(missing_ok=True)
    r = subprocess.run(
        ["hdiutil", "create", "-volname", f"{NAAM} {VERSIE}", "-srcfolder", str(werk),
         "-ov", "-format", "UDZO", str(doel)],
        capture_output=True, text=True,
    )
    shutil.rmtree(werk, ignore_errors=True)
    if r.returncode != 0:
        print("  dmg overgeslagen:", (r.stderr or "").strip()[:200])
        return None
    return doel


def main() -> int:
    p = argparse.ArgumentParser(description="Bouw een dubbelklikbare BeatCut-app.")
    p.add_argument("--alles", action="store_true", help="Ook voor het andere platform")
    p.add_argument("--bron", action="store_true",
                   help="De app naar de broncode laten wijzen in plaats van "
                        "de ingevroren engine (voor tijdens het bouwen)")
    p.add_argument("--dmg", action="store_true", help="Ook een schijfkopie maken")
    args = p.parse_args()

    UIT.mkdir(parents=True, exist_ok=True)
    gemaakt: list[Path] = []

    if sys.platform == "darwin" or args.alles:
        if sys.platform == "darwin":
            app = maak_macos(ingevroren=not args.bron)
            gemaakt.append(app)
            if args.dmg:
                d = maak_dmg(app)
                if d:
                    gemaakt.append(d)
        else:
            print("macOS-app overgeslagen: die kan alleen op een Mac gebouwd worden.")
    if sys.platform.startswith("win") or args.alles:
        gemaakt.append(maak_windows())

    print(f"\n{NAAM} {VERSIE}")
    for g in gemaakt:
        maat = ""
        if g.is_file():
            maat = f"  ({g.stat().st_size / 1_000_000:.0f} MB)"
        print(f"  {g}{maat}")
    print("\nSleep hem naar Programma's of naar je Dock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
