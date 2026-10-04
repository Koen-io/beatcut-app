"""Welke stijl past bij dit materiaal?

De gebruiker hoeft dit niet te weten. Alles wat nodig is om het te bepalen
staat al in `analysis.json`: hoeveel er beweegt, hoe vaak er een gezicht in
beeld is, hoe onrustig de camera is, en of er gepraat wordt. Dat zijn precies
de dingen die het verschil maken tussen een vlog en een landschapsfilm.

Geen model, geen drempelwaarde die uit de lucht komt vallen: elke stijl heeft
een profiel, en we kiezen de stijl waarvan het profiel het dichtst bij het
gemeten materiaal ligt. Zo is de uitkomst uit te leggen ("veel gezichten en
spraak, weinig beweging → vlog") en bij te stellen door één getal te
veranderen.

De uitkomst is een voorstel, geen besluit: de wizard laat het zien en de
gebruiker mag het met één klik overrulen.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

SIGNALEN = ("beweging", "gezicht", "shake", "vlakheid", "spraak")

# Profiel per stijl. Geen gemeten gemiddelde maar het karakter van de stijl:
# zo ziet materiaal er typisch uit als deze montage erbij past.
#
#                       beweging  gezicht  shake  vlakheid  spraak
PROFIELEN: dict[str, tuple[float, ...]] = {
    "landschap":  (0.20, 0.03, 0.10, 0.30, 0.05),
    "luchtvaart": (0.40, 0.02, 0.06, 0.55, 0.05),
    "reis":       (0.45, 0.15, 0.22, 0.18, 0.35),
    "vlog":       (0.30, 0.65, 0.30, 0.15, 0.75),
    "actie":      (0.75, 0.12, 0.55, 0.12, 0.15),
}

# Hoe zwaar elk signaal weegt. Gezichten zijn de scherpste onderscheider - die
# zijn er wel of niet. `vlakheid` doet er vooral toe om luchtbeelden (veel
# lucht en water in beeld) te scheiden van beelden op ooghoogte; zonder dat
# signaal won `luchtvaart` op dit materiaal van `reis`, en dat klopte niet.
# `spraak` weegt bewust licht: buiten pikt de stiltedetectie ook wind op.
WEGING = (1.0, 1.6, 0.9, 1.1, 0.6)

# Vanaf wanneer telt een segment als "hier zit een gezicht in" en "hier wordt
# gepraat". Een deel-van-het-materiaal zegt meer dan een gemiddelde: één
# segment met een gezicht in twintig is iets anders dan overal een half hoofd.
GEZICHT_DREMPEL = 0.15
SPRAAK_DREMPEL = 0.55

UITLEG = {
    "landschap": "rustige, scherpe beelden zonder mensen in beeld",
    "luchtvaart": "overzichtsbeelden met trage, vloeiende beweging",
    "reis": "een mix van rustige en bewegende beelden",
    "vlog": "veel gezichten en gesproken woord",
    "actie": "veel beweging en een bewegende camera",
}


@dataclass
class Voorstel:
    stijl: str
    zekerheid: float  # 0..1, hoe duidelijk de winnaar wint van nummer twee
    gemeten: dict[str, float]
    uitleg: str
    volgorde: list[tuple[str, float]]

    def zin(self) -> str:
        """Eén zin die een mens begrijpt."""
        aanhef = "Dit lijkt op" if self.zekerheid >= 0.35 else "Dit zou kunnen zijn:"
        return f"{aanhef} {UITLEG.get(self.stijl, self.stijl)}."


def _meet(analyse: dict) -> dict[str, float]:
    """Wat voor materiaal is dit, in vijf getallen.

    Over segmenten, niet over shots: segmenten zijn de stukken die de
    regisseur ook echt kan gebruiken. Een clip die voor 80 % uit onbruikbaar
    materiaal bestaat moet de stijlkeuze niet bepalen.

    **Mediaan, geen gemiddelde**, voor beweging, shake en vlakheid. Gemeten op
    dit materiaal: `geluid` had een gemiddelde van 0,39 maar een mediaan van
    0,11 - een handvol segmenten met wind trok het gemiddelde omhoog en dat
    maakte van een reisvideo bijna een vlog.

    Voor gezichten en spraak is niet de hoogte interessant maar het aandeel:
    in hoeveel van je beelden zit een gezicht, hoe vaak wordt er gepraat.
    """
    segmenten = [s.get("onderdelen") or {} for s in analyse.get("segmenten", [])]
    if not segmenten:
        return {k: 0.0 for k in SIGNALEN}

    def mediaan(sleutel: str) -> float:
        waarden = [float(s.get(sleutel, 0.0)) for s in segmenten]
        return float(statistics.median(waarden)) if waarden else 0.0

    def aandeel(sleutel: str, drempel: float) -> float:
        return sum(1 for s in segmenten if float(s.get(sleutel, 0.0)) > drempel) / len(segmenten)

    return {
        "beweging": mediaan("beweging"),
        "gezicht": aandeel("gezicht", GEZICHT_DREMPEL),
        "shake": mediaan("shake"),
        "vlakheid": mediaan("vlakheid"),
        "spraak": aandeel("geluid", SPRAAK_DREMPEL),
    }


def kies(analyse: dict) -> Voorstel:
    gem = _meet(analyse)
    gemeten = tuple(gem[k] for k in SIGNALEN)

    afstanden: list[tuple[str, float]] = []
    for naam, profiel in PROFIELEN.items():
        afstand = sum(
            w * (m - p) ** 2 for w, m, p in zip(WEGING, gemeten, profiel)
        ) ** 0.5
        afstanden.append((naam, afstand))
    afstanden.sort(key=lambda x: x[1])

    beste, beste_afstand = afstanden[0]
    tweede_afstand = afstanden[1][1] if len(afstanden) > 1 else beste_afstand + 1.0
    # Hoe verder nummer twee weg ligt, hoe zekerder de keuze. Bij een gelijke
    # stand is dat 0, en dan zegt de wizard "dit zou kunnen zijn".
    zekerheid = 0.0 if tweede_afstand <= 0 else min(
        1.0, max(0.0, (tweede_afstand - beste_afstand) / tweede_afstand)
    )

    return Voorstel(
        stijl=beste,
        zekerheid=round(zekerheid, 3),
        gemeten={k: round(v, 3) for k, v in gem.items()},
        uitleg=UITLEG.get(beste, beste),
        volgorde=[(n, round(a, 3)) for n, a in afstanden],
    )
