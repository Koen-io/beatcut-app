"""ffmpeg ophalen als de gebruiker het niet heeft.

BeatCut kan zonder ffmpeg niets: geen proxies, geen analyse, geen render.
Iemand die de app net geïnstalleerd heeft, wil daar geen terminal voor open
hoeven trekken.

**Waarom het niet gewoon meegebakken zit.** ffmpeg bestaat in twee smaken:
een LGPL-build die je mag meeleveren, en een GPL-build met meer codecs die
je hele programma onder de GPL zou trekken zodra je hem meelevert. De
kant-en-klare builds die je online vindt zijn bijna allemaal GPL. Zelf een
LGPL-build compileren voor drie platforms is een dag werk en een doorlopende
onderhoudsklus.

De uitweg die andere apps ook nemen: **de gebruiker haalt hem zelf op.**
Downloaden voor eigen gebruik mag altijd; het is verspreiden dat aan regels
gebonden is. Deze module doet dat op één klik, zet het resultaat in de
steunmap van de app, en daarna vindt `paths.ffmpeg()` hem vanzelf.
"""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

from . import paths

# Waar de statische builds vandaan komen. Beide zijn de gebruikelijke bron
# voor hun platform en leveren één bestand zonder afhankelijkheden.
BRONNEN: dict[str, dict[str, str]] = {
    "darwin": {
        "ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    },
    "win32": {
        # Eén archief met beide programma's erin.
        "bundel": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    },
    "linux": {
        "bundel": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    },
}

def doelmap() -> Path:
    return paths.steun_map() / "bin"


def ontbreekt() -> list[str]:
    """Welke van de twee programma's er nog niet zijn."""
    mist = []
    for naam in ("ffmpeg", "ffprobe"):
        if paths._zoek_programma(naam) is None:
            mist.append(naam)
    return mist


def _uitvoerbaar(pad: Path) -> None:
    pad.chmod(pad.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _haal(url: str, doel: Path, *, log) -> Path:
    import urllib.request

    log(f"Ophalen: {url.split('/')[2]} …")
    with urllib.request.urlopen(url, timeout=120) as r, doel.open("wb") as f:
        shutil.copyfileobj(r, f)
    return doel


def _pak_uit(archief: Path, naar: Path, namen: tuple[str, ...], *, log) -> list[Path]:
    """Haal alleen de programma's zelf uit het archief, waar ze ook zitten."""
    uit: list[Path] = []
    naar.mkdir(parents=True, exist_ok=True)

    def bewaar(naam: str, lees) -> None:
        kaal = Path(naam).name
        basis = kaal[:-4] if kaal.endswith(".exe") else kaal
        if basis not in namen:
            return
        doel = naar / kaal
        with doel.open("wb") as f:
            shutil.copyfileobj(lees, f)
        _uitvoerbaar(doel)
        uit.append(doel)
        log(f"  {kaal}")

    if archief.suffix == ".zip" or zipfile.is_zipfile(archief):
        with zipfile.ZipFile(archief) as z:
            for lid in z.namelist():
                if lid.endswith("/"):
                    continue
                with z.open(lid) as f:
                    bewaar(lid, f)
    else:
        with tarfile.open(archief) as t:
            for lid in t.getmembers():
                if not lid.isfile():
                    continue
                f = t.extractfile(lid)
                if f is not None:
                    bewaar(lid.name, f)
    return uit


def installeer_ffmpeg(*, log=print) -> list[Path]:
    """Haal ffmpeg en ffprobe op en zet ze in de steunmap van de app."""
    import sys

    sleutel = "darwin" if sys.platform == "darwin" else (
        "win32" if sys.platform.startswith("win") else "linux"
    )
    bron = BRONNEN[sleutel]
    doel = doelmap()
    doel.mkdir(parents=True, exist_ok=True)
    gemaakt: list[Path] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if "bundel" in bron:
            archief = _haal(bron["bundel"], tmp / "ffmpeg-bundel", log=log)
            gemaakt += _pak_uit(archief, doel, ("ffmpeg", "ffprobe"), log=log)
        else:
            for naam, url in bron.items():
                archief = _haal(url, tmp / f"{naam}.zip", log=log)
                gemaakt += _pak_uit(archief, doel, (naam,), log=log)

    if not gemaakt:
        raise RuntimeError("Het archief bevatte geen ffmpeg. Probeer het later opnieuw.")

    # macOS zet een quarantainevlag op alles wat je downloadt; die zorgt dat
    # het programma bij de eerste aanroep geweigerd wordt.
    if sleutel == "darwin":
        for p in gemaakt:
            os.system(f'xattr -d com.apple.quarantine "{p}" 2>/dev/null')

    log(f"Klaar. Opgeslagen in {doel}")
    return gemaakt


# --------------------------------------------------------------------------
# Node, HyperFrames en de browser — voor titels in de export
# --------------------------------------------------------------------------
#
# Die wonen sinds 03-10-2026 in `onderdelen.py`: met vaste versies, een
# gepinde sha256, hervatten, annuleren en voortgang. Hier stond een tweede,
# simpelere kopie die de nieuwste LTS ophaalde — twee installateurs voor
# hetzelfde is één te veel.


def zet_alles_klaar(*, log=print, melden=None) -> None:
    """Alles wat een verse installatie nog mist, in één keer.

    `melden(fase, klaar, totaal)` laat het venster zien hoe ver het is. Elke
    stap is los over te slaan: ontbreekt de titelmotor, dan werkt de rest nog
    steeds, alleen zonder titels in beeld.
    """
    from . import onderdelen

    zeg = melden or (lambda *_a, **_k: None)

    if ontbreekt():
        zeg("ffmpeg", 0, 1)
        installeer_ffmpeg(log=log)
    zeg("ffmpeg", 1, 1)

    def melder(stap, gedaan, totaal, tekst):
        log(tekst)
        zeg(stap, gedaan, totaal)

    zeg("titels", 0, 1)
    onderdelen.installeer(melder=melder)
    zeg("titels", 1, 1)
