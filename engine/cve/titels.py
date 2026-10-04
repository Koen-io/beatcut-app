"""Titels voorstellen op basis van wat er gemeten is.

De montage loopt langs plekken en dagen. Elke keer dat de video naar een
andere plaats of een andere dag springt, is dat een natuurlijk moment voor
een titel — precies zoals een reisverslag hoofdstukken heeft.

Alles hier komt uit meetbare feiten: de opnamelocatie uit het bestand, de
opnamedatum, de hoogte. Geen model, geen internet, geen verzinsels. Wat er
uitkomt is saai maar waar: "Garmisch-Partenkirchen · 690 m".

Wie mooiere titels wil, zet in de wizard de AI-variant aan. Die kijkt naar
de beelden en schrijft iets persoonlijkers. Dat is een upgrade, geen
vereiste: zonder internet werkt bovenstaande gewoon door.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import geo

# Hoe ver twee opnames uit elkaar moeten liggen voordat het een andere plek
# is. Onder deze afstand is het hetzelfde dorp of dezelfde vallei.
NIEUWE_PLEK_KM = 12.0

# Een plek moet minstens zoveel van de montage beslaan om een titel waard te
# zijn. Anders krijg je een titel over een shot van twee seconden.
MIN_DEEL = 0.045

# Minimale afstand tussen twee titels. Zonder dit buitelen ze over elkaar heen
# in het begin van de montage, waar de shots het kortst zijn.
MIN_AFSTAND_S = 9.0

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december"]


@dataclass
class Hoofdstuk:
    """Een aaneengesloten stuk montage op één plek, op één dag."""

    start: float
    eind: float
    plaats: str = ""
    land: str = ""
    hoogte: float | None = None
    datum: str = ""          # ISO, zoals in de metadata
    clips: list[str] = field(default_factory=list)

    @property
    def duur(self) -> float:
        return round(self.eind - self.start, 3)


def _datum_kort(iso: str) -> str:
    """"2026-06-10T20:46:48+0200" wordt "10 juni"."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.fromisoformat(iso[:19])
        except ValueError:
            return ""
    return f"{d.day} {MAANDEN[d.month - 1]}"


def _dagsleutel(iso: str) -> str:
    return iso[:10] if iso else ""


def hoofdstukken(edl_video: list[dict], clips: dict[str, dict], *,
                 met_internet: bool = False) -> list[Hoofdstuk]:
    """Deel de montage op in stukken die over dezelfde plek en dag gaan.

    `clips` is de clipinformatie uit `analysis.json`, op id. Daar zit de
    locatie in die tijdens de ingest is meegeschreven.
    """
    uit: list[Hoofdstuk] = []
    for b in edl_video:
        c = clips.get(b.get("clip", "")) or {}
        loc = c.get("locatie") or {}
        datum = c.get("opgenomen") or ""
        start = float(b.get("tijdlijn_start", 0))
        eind = start + float(b.get("duur", 0))

        hoort_erbij = False
        if uit:
            vorige = uit[-1]
            zelfde_dag = _dagsleutel(datum) == _dagsleutel(vorige.datum)
            if not loc or vorige.hoogte is None and not vorige.plaats:
                # Zonder locatie kunnen we alleen op de dag afgaan.
                hoort_erbij = zelfde_dag
            else:
                d = _afstand_tot(vorige, loc)
                hoort_erbij = zelfde_dag and (d is None or d <= NIEUWE_PLEK_KM)
        if hoort_erbij:
            uit[-1].eind = eind
            uit[-1].clips.append(b.get("clip", ""))
            continue

        h = Hoofdstuk(start=start, eind=eind, datum=datum, clips=[b.get("clip", "")])
        if loc:
            h._lat, h._lon = loc.get("lat"), loc.get("lon")  # type: ignore[attr-defined]
            h.hoogte = loc.get("hoogte")
        uit.append(h)

    # Plaatsnamen pas opzoeken als de indeling vaststaat: dat scheelt een
    # opzoeking per shot, en online zou dat pas echt zonde zijn.
    for h in uit:
        lat = getattr(h, "_lat", None)
        lon = getattr(h, "_lon", None)
        if lat is None or lon is None:
            continue
        p = geo.zoek(lat, lon, met_internet=met_internet)
        if p:
            h.plaats = geo.leesbaar(p.naam)
            h.land = p.land
    return uit


def _afstand_tot(h: Hoofdstuk, loc: dict) -> float | None:
    lat, lon = getattr(h, "_lat", None), getattr(h, "_lon", None)
    if lat is None or lon is None or "lat" not in loc:
        return None
    return geo.afstand_km(lat, lon, loc["lat"], loc["lon"])


def voorstel(edl_video: list[dict], clips: dict[str, dict], *,
             hoofdtitel: str = "", met_internet: bool = False,
             maximaal: int = 6) -> list[dict]:
    """Titels voor de hele montage, in de volgorde waarin ze verschijnen.

    Teruggave per titel: `tijdlijn_start`, `duur`, `titel`, `eyebrow`,
    `onder` en `waarom`. De laatste is er zodat de wizard kan laten zien
    waar een titel vandaan komt — een titel die uit het niets verschijnt
    voelt als een gok.
    """
    stukken = [h for h in hoofdstukken(edl_video, clips, met_internet=met_internet)]
    totaal = max(h.eind for h in stukken) if stukken else 0.0
    if totaal <= 0:
        return []

    # De regisseur wisselt bewust af tussen plekken, dus dezelfde plaats komt
    # verspreid over de montage terug. Twee regels houden dat leesbaar:
    # elke plek krijgt hoogstens één titel, en twee titels liggen nooit vlak
    # bij elkaar.
    #
    # Belangrijk: we kijken naar *alle* stukken van een plek, niet alleen het
    # langste. Botst het langste stuk van Uitgeest met de titel ervoor, dan
    # kan een later stuk van diezelfde plek nog prima. Alleen het langste
    # bekijken liet hier drie van de vier plaatsen wegvallen.
    kandidaten = [
        h for h in stukken
        if h.duur / totaal >= MIN_DEEL and (h.plaats or h.datum)
    ]
    kandidaten.sort(key=lambda h: -h.duur)

    gekozen: list[Hoofdstuk] = []
    gebruikt: set[str] = set()

    # De openingstitel hoort aan het begin van de video en nergens anders.
    # Zonder deze regel landt hij op het langste hoofdstuk, en dat kan
    # halverwege liggen.
    if stukken:
        eerste = stukken[0]
        eerste.opening = True  # type: ignore[attr-defined]
        gekozen.append(eerste)
        gebruikt.add(eerste.plaats or _dagsleutel(eerste.datum))

    for h in kandidaten:
        if len(gekozen) >= maximaal:
            break
        sleutel = h.plaats or _dagsleutel(h.datum)
        if sleutel in gebruikt:
            continue
        if any(abs(h.start - g.start) < MIN_AFSTAND_S for g in gekozen):
            continue
        gekozen.append(h)
        gebruikt.add(sleutel)
    bruikbaar = sorted(gekozen, key=lambda h: h.start)

    uit: list[dict] = []
    vorige_dag = ""
    for h in bruikbaar:
        datum = _datum_kort(h.datum)
        nieuwe_dag = _dagsleutel(h.datum) != vorige_dag
        vorige_dag = _dagsleutel(h.datum)

        if getattr(h, "opening", False) and hoofdtitel:
            titel, eyebrow = hoofdtitel, (h.plaats or datum)
        elif getattr(h, "opening", False) and not h.plaats:
            continue
        elif h.plaats:
            titel = h.plaats
            eyebrow = datum if nieuwe_dag else ""
        elif datum:
            titel, eyebrow = datum, ""
        else:
            continue

        onder = ""
        if h.hoogte is not None and h.hoogte >= 400:
            onder = f"{round(h.hoogte / 10) * 10:.0f} m"

        uit.append({
            "tijdlijn_start": round(h.start + min(0.6, h.duur * 0.15), 3),
            "duur": round(min(3.5, max(2.0, h.duur * 0.35)), 3),
            "titel": titel,
            "eyebrow": eyebrow,
            "onder": onder,
            # De ruwe datum erbij: de titelstijl "Datumstempel" zet hem als
            # camcorderstempel, en daar hoort een ander formaat bij dan "14 juni".
            "datum_iso": h.datum or "",
            # En de ruwe coordinaten: de stijl "Coordinaten" zet ze eronder.
            # Zonder GPS blijven ze leeg en valt die stijl terug op plaats en
            # datum -- dat is nog steeds gemeten, alleen minder bijzonder.
            "lat": getattr(h, "_lat", None),
            "lon": getattr(h, "_lon", None),
            "waarom": _waarom(h, datum),
        })
    return uit


def _waarom(h: Hoofdstuk, datum: str) -> str:
    delen = []
    if h.plaats:
        delen.append(f"opgenomen bij {h.plaats}")
    if datum:
        delen.append(f"op {datum}")
    if h.hoogte is not None and h.hoogte >= 400:
        delen.append(f"op {h.hoogte:.0f} meter hoogte")
    delen.append(f"{h.duur:.0f}s montage")
    return ", ".join(delen)
