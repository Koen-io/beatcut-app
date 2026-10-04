"""Van coördinaten naar een plaatsnaam.

iPhones en de meeste camera's schrijven de opnamelocatie in het bestand.
Dat is gratis informatie waar een titel uit te maken valt die klopt:
"Garmisch-Partenkirchen · 690 m" hoeft niemand te verzinnen.

**Offline is de standaard.** De werk-editie moet zonder internet kunnen
draaien, en je opnamelocaties horen niet zomaar naar een externe dienst te
gaan. Daarom zoeken we in een lijst met plaatsen die één keer wordt
opgehaald en daarna op schijf staat.

Online opzoeken is preciezer — straatnamen, bergtoppen, meren — maar dat
zet je zelf aan, en dan weet je ook dat je coördinaten het huis uit gaan.

De lijst komt van GeoNames (CC BY 4.0, https://www.geonames.org/).
`cve geo --installeer` haalt hem op: `cities15000` is 1,5 MB en dekt elke
plaats vanaf 15.000 inwoners; `cities5000` is drie keer zo groot en zit
dichter op de kleinere dorpen.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import paths

BRONNEN = {
    "cities15000": "https://download.geonames.org/export/dump/cities15000.zip",
    "cities5000": "https://download.geonames.org/export/dump/cities5000.zip",
    "cities1000": "https://download.geonames.org/export/dump/cities1000.zip",
}

# Verder dan dit van de dichtstbijzijnde plaats: dan zegt die naam niets meer
# over waar je stond. Op zee of in de bergen gebeurt dat.
MAX_AFSTAND_KM = 30.0


def gegevens_pad() -> Path:
    return paths.VENDOR / "geonames" / "plaatsen.tsv"


@dataclass
class Plaats:
    naam: str
    land: str  # ISO-landcode
    lat: float
    lon: float
    inwoners: int = 0
    afstand_km: float = 0.0

    def naar_dict(self) -> dict:
        return {
            "naam": self.naam,
            "land": self.land,
            "afstand_km": round(self.afstand_km, 1),
            "inwoners": self.inwoners,
        }


# --------------------------------------------------------------------------
# Coördinaten uit het bestand
# --------------------------------------------------------------------------

# ISO 6709, zoals Apple hem schrijft: "+47.5007+011.0995+688.482/"
_ISO6709 = re.compile(
    r"([+-]\d{1,3}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)(?:([+-]\d+(?:\.\d+)?))?"
)


def uit_tags(tags: dict[str, str]) -> dict | None:
    """Haal breedte, lengte en hoogte uit de metadata van een clip.

    Werkt voor Apple (`com.apple.quicktime.location.ISO6709`) en voor de
    algemene `location`-tag die ffmpeg voor andere camera's uitleest.
    """
    ruw = ""
    for sleutel in (
        "com.apple.quicktime.location.ISO6709",
        "location",
        "location-eng",
    ):
        if tags.get(sleutel):
            ruw = str(tags[sleutel])
            break
    if not ruw:
        return None

    m = _ISO6709.search(ruw)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    hoogte = float(m.group(3)) if m.group(3) else None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        return None  # 0,0 is "geen fix", niet de Golf van Guinee

    uit = {"lat": round(lat, 5), "lon": round(lon, 5)}
    if hoogte is not None:
        uit["hoogte"] = round(hoogte, 1)
    try:
        uit["nauwkeurigheid"] = round(
            float(tags.get("com.apple.quicktime.location.accuracy.horizontal", 0)), 1
        )
    except (TypeError, ValueError):
        pass
    return uit


# --------------------------------------------------------------------------
# Afstand en opzoeken
# --------------------------------------------------------------------------


def afstand_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Goed genoeg: we zoeken een plaatsnaam, geen landingsbaan."""
    r = 6371.0
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_lijst: list[tuple[float, float, str, str, int]] | None = None


def _laad() -> list[tuple[float, float, str, str, int]]:
    """Lees het plaatsenbestand één keer in het geheugen.

    Formaat per regel: lat, lon, naam, landcode, inwoners — tab-gescheiden.
    Dat is een uitgeklede versie van de GeoNames-tabel; `installeer()` maakt
    hem. Zo hoeven we bij elke start geen 200 MB te doorlopen.
    """
    global _lijst
    if _lijst is not None:
        return _lijst
    pad = gegevens_pad()
    uit: list[tuple[float, float, str, str, int]] = []
    if pad.exists():
        for regel in pad.read_text(encoding="utf-8").splitlines():
            delen = regel.split("\t")
            if len(delen) < 5:
                continue
            try:
                uit.append(
                    (float(delen[0]), float(delen[1]), delen[2], delen[3], int(delen[4] or 0))
                )
            except ValueError:
                continue
    _lijst = uit
    return uit


def dichtstbij(lat: float, lon: float) -> Plaats | None:
    """De dichtstbijzijnde plaats uit het offline bestand."""
    lijst = _laad()
    if not lijst:
        return None

    # Eerst grof filteren op een venster om de coördinaat heen: over tienduizend
    # regels rekent dat een stuk sneller dan overal de haversine op loslaten.
    graden = MAX_AFSTAND_KM / 111.0
    breedte = graden / max(0.15, math.cos(math.radians(lat)))
    kandidaten = [
        p for p in lijst
        if abs(p[0] - lat) <= graden and abs(p[1] - lon) <= breedte
    ]
    if not kandidaten:
        return None

    beste, beste_d = None, 1e9
    for plat, plon, naam, land, inw in kandidaten:
        d = afstand_km(lat, lon, plat, plon)
        # Grotere plaatsen mogen iets verder weg liggen: bij een dorpje naast
        # een stad is de stad meestal het antwoord dat een mens zou geven.
        gewogen = d / (1.0 + min(0.5, math.log10(max(inw, 1)) / 12.0))
        if gewogen < beste_d:
            beste, beste_d = (plat, plon, naam, land, inw), gewogen
    if beste is None:
        return None
    d = afstand_km(lat, lon, beste[0], beste[1])
    if d > MAX_AFSTAND_KM:
        return None
    return Plaats(naam=beste[2], land=beste[3], lat=beste[0], lon=beste[1],
                  inwoners=beste[4], afstand_km=d)


def online(lat: float, lon: float, *, taal: str = "nl") -> Plaats | None:
    """Vraag het aan OpenStreetMap. Alleen als de gebruiker dat aanzet.

    Bewust geen afhankelijkheid: `urllib` zit in Python zelf, en zo blijft de
    installatie klein. Faalt het - geen internet, dienst plat, te druk - dan
    is dat geen fout maar gewoon geen antwoord.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    from . import __version__

    vraag = urllib.parse.urlencode(
        {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2", "zoom": "12"}
    )
    verzoek = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?{vraag}",
        headers={
            # Nominatim vraagt om een herkenbare naam; anders word je geweigerd.
            "User-Agent": f"claude-video-editor/{__version__}",
            "Accept-Language": taal,
        },
    )
    try:
        with urllib.request.urlopen(verzoek, timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None

    a = d.get("address") or {}
    naam = (
        a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
        or a.get("suburb") or a.get("county") or d.get("name") or ""
    )
    if not naam:
        return None
    return Plaats(naam=naam, land=(a.get("country_code") or "").upper(),
                  lat=lat, lon=lon)


def zoek(lat: float, lon: float, *, met_internet: bool = False) -> Plaats | None:
    """Offline eerst. Alleen als dat niets oplevert én het mag, online."""
    p = dichtstbij(lat, lon)
    if p is not None:
        return p
    return online(lat, lon) if met_internet else None


# --------------------------------------------------------------------------
# Het bestand ophalen
# --------------------------------------------------------------------------


def installeer(soort: str = "cities15000", *, log=print) -> Path:
    """Haal de plaatsenlijst op en schrijf hem uitgekleed weg.

    Eén keer, net als het whisper-model. Daarna is alles offline.
    """
    import io
    import urllib.request
    import zipfile

    if soort not in BRONNEN:
        raise ValueError(f"onbekende lijst {soort!r}; kies uit {', '.join(BRONNEN)}")

    doel = gegevens_pad()
    doel.parent.mkdir(parents=True, exist_ok=True)
    log(f"Plaatsenlijst {soort} ophalen van geonames.org …")
    with urllib.request.urlopen(BRONNEN[soort], timeout=120) as r:
        rauw = r.read()

    regels: list[str] = []
    with zipfile.ZipFile(io.BytesIO(rauw)) as z:
        with z.open(f"{soort}.txt") as f:
            for regel in io.TextIOWrapper(f, encoding="utf-8"):
                d = regel.split("\t")
                if len(d) < 15:
                    continue
                # 1 naam · 4 lat · 5 lon · 8 landcode · 14 inwoners
                regels.append(f"{d[4]}\t{d[5]}\t{d[1]}\t{d[8]}\t{d[14]}")

    doel.write_text("\n".join(regels) + "\n", encoding="utf-8")
    global _lijst
    _lijst = None
    log(f"{len(regels)} plaatsen opgeslagen in {doel}")
    return doel


def is_geinstalleerd() -> bool:
    return bool(_laad())


# --------------------------------------------------------------------------
# Hulp bij het schrijven van titels
# --------------------------------------------------------------------------


def leesbaar(naam: str) -> str:
    """Maak er iets van dat je in beeld durft te zetten.

    GeoNames schrijft sommige namen met toevoegingen tussen haakjes en met
    tekens die in een titel raar staan.
    """
    naam = re.sub(r"\s*\([^)]*\)", "", naam).strip()
    # Accenten blijven staan (Garmisch-Partenkirchen hoort met streepje), maar
    # combinerende tekens normaliseren we zodat de letterset ze kan tekenen.
    return unicodedata.normalize("NFC", naam)
