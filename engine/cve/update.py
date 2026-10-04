"""Kijken of er een nieuwe versie van BeatCut is.

Bewust klein gehouden. De app vraagt bij het starten één keer aan GitHub of
er een nieuwere release is, en meldt dat in de interface met een link. Meer
niet: geen achtergrondproces, geen zelf downloaden, geen herstart.

Waarom niet meer: automatisch bijwerken vraagt om ondertekende bestanden en
een handtekeningcontrole, anders installeer je wat een tussenpersoon je
voorschotelt. Dat hoort bij de Tauri-schil (zie `installer/LEESMIJ.md`).
Melden dát er iets is, is negentig procent van het nut en kost dit bestand.

De controle mag nooit iets ophouden. Geen internet, GitHub plat, een
bedrijfsnetwerk dat het blokkeert: dan is er gewoon geen antwoord en gaat
alles door zoals het was.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__, paths

# **Deze repo moet openbaar zijn.** De app vraagt het zonder in te loggen -
# hij heeft geen token en die zou ook niet in een programma horen dat je
# uitdeelt. Op een privérepo geeft GitHub 404 en werkt de controle niet; dat
# is hier eerst misgegaan.
#
# Daarom twee repo's: `beatcut` met de broncode blijft privé, en
# `beatcut-releases` is openbaar en bevat alleen een README. De installers
# hangen daar als release-assets aan, en die staan buiten de git-geschiedenis
# - de repo zelf blijft dus een paar kilobyte, hoe vaak je ook uitgeeft.
REPO = os.environ.get("BEATCUT_RELEASES_REPO", "Koen-io/beatcut-releases")
API = f"https://api.github.com/repos/{REPO}/releases/latest"

# Hoe lang een antwoord bruikbaar blijft. Eén keer per dag is ruim genoeg;
# vaker is alleen maar verkeer zonder nieuws.
BEWAARTIJD = 24 * 3600


@dataclass
class Uitkomst:
    huidig: str
    nieuwste: str = ""
    nieuwer: bool = False
    url: str = ""
    gekeken: float = 0.0
    fout: str = ""

    def naar_dict(self) -> dict:
        return asdict(self)


def _cache_pad() -> Path:
    return paths.ROOT / "vendor" / "update.json"


def _delen(versie: str) -> tuple[int, ...]:
    """"v0.2.10" wordt (0, 2, 10). Alles wat geen getal is valt weg."""
    return tuple(int(x) for x in re.findall(r"\d+", versie)) or (0,)


def is_nieuwer(kandidaat: str, huidig: str) -> bool:
    a, b = _delen(kandidaat), _delen(huidig)
    # Even lang maken, anders is (0, 2) groter dan (0, 2, 1) op lengte.
    lengte = max(len(a), len(b))
    a += (0,) * (lengte - len(a))
    b += (0,) * (lengte - len(b))
    return a > b


def _uit_cache() -> Uitkomst | None:
    pad = _cache_pad()
    if not pad.exists():
        return None
    try:
        d = json.loads(pad.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - float(d.get("gekeken", 0)) > BEWAARTIJD:
        return None
    # De opgeslagen versie kan van een oudere installatie zijn; opnieuw
    # vergelijken met wat er nú draait.
    d["huidig"] = __version__
    d["nieuwer"] = bool(d.get("nieuwste")) and is_nieuwer(d["nieuwste"], __version__)
    return Uitkomst(**{k: v for k, v in d.items() if k in Uitkomst.__annotations__})


def kijk(*, forceer: bool = False, timeout: float = 6.0) -> Uitkomst:
    """Is er een nieuwere versie? Faalt nooit, geeft hoogstens niets terug."""
    if not forceer:
        eerder = _uit_cache()
        if eerder is not None:
            return eerder

    import urllib.error
    import urllib.request

    uit = Uitkomst(huidig=__version__, gekeken=time.time())
    verzoek = urllib.request.Request(
        API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"BeatCut/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        uit.nieuwste = str(d.get("tag_name") or "").lstrip("v")
        uit.url = str(d.get("html_url") or "")
        uit.nieuwer = bool(uit.nieuwste) and is_nieuwer(uit.nieuwste, __version__)
    except urllib.error.HTTPError as e:
        # 404 betekent hier bijna altijd: de repo is privé, of er is nog geen
        # release. Allebei geen storing waar de gebruiker iets mee moet.
        uit.fout = "geen release gevonden" if e.code == 404 else f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError) as e:
        uit.fout = type(e).__name__

    try:
        pad = _cache_pad()
        pad.parent.mkdir(parents=True, exist_ok=True)
        pad.write_text(json.dumps(uit.naar_dict(), indent=1), encoding="utf-8")
    except OSError:
        pass
    return uit
