"""Fase 2 - segmentatie binnen een clip.

Het inzicht uit fase 1: dit materiaal bestaat uit doorlopende opnames. Van 21
clips had er precies een een tweede shot. Scenedetectie levert dus niets op.
De vraag is niet "waar zit de knip" maar "welke twee seconden uit deze
achttien zijn de beste".

Daarom schuiven we een venster over de clip, geven elk venster een score, en
houden de toppen over die elkaar niet overlappen. Puur rekenwerk, geen model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Kandidaatlengtes in seconden. Moet de langste `max_shot` van alle stijlen
# dekken: de luchtvaartstijl vraagt om shots tot 9 seconden, en als er geen
# kandidaat van die lengte bestaat vindt de regisseur helemaal niets.
VENSTERS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.5, 8.0, 10.0)

# Minimale afstand tussen twee gekozen segmenten binnen dezelfde clip, zodat
# we niet twee keer bijna hetzelfde moment pakken.
MIN_AFSTAND = 1.0


@dataclass
class Gewichten:
    """Per videotype anders. Komt uit styles/<type>.md.

    Let op welke signalen echt onderscheiden. `licht` als "meer is beter"
    bleek waardeloos: buitenopnames zaten allemaal op 1.00. Het is nu een
    straf voor te donker, en verder niets. Hetzelfde gold voor `geluid`:
    stiltedetectie op -32 dB vindt geen spraak maar wind, dus dat signaal
    staat in de actiestijl op nul.
    """

    beweging: float = 0.30
    scherpte: float = 0.25
    belichting: float = 0.15
    shake: float = -0.10
    vlakheid: float = -0.15
    gezicht: float = 0.15
    te_donker: float = -0.30
    geluid: float = 0.0
    # Hoeveel een langer segment mag winnen van een korter. 0 = geen voorkeur.
    lengte_voorkeur: float = 0.06
    # Hoe zwaar het slechtste moment in een venster meetelt. Een segment dat
    # gemiddeld goed is maar halverwege wegzakt, is onbruikbaar in de montage.
    consistentie: float = 0.35

    @classmethod
    def van_dict(cls, d: dict) -> Gewichten:
        bekend = {k: float(v) for k, v in d.items() if k in cls.__annotations__}
        return cls(**bekend)

    def signalen(self) -> dict[str, float]:
        """Alleen de gewichten die op een meetreeks slaan."""
        uit = dict(self.__dict__)
        uit.pop("lengte_voorkeur", None)
        uit.pop("consistentie", None)
        return uit


@dataclass
class Segment:
    clip: str
    scene: int
    start: float
    eind: float
    score: float
    onderdelen: dict[str, float] = field(default_factory=dict)
    hash: int = 0

    @property
    def duur(self) -> float:
        return round(self.eind - self.start, 3)


def _reeks(bron: dict, naam: str, lengte: int) -> np.ndarray:
    waarden = bron.get(naam)
    if not waarden:
        return np.zeros(lengte, dtype=float)
    arr = np.asarray(waarden, dtype=float)
    if len(arr) < lengte:
        arr = np.pad(arr, (0, lengte - len(arr)), mode="edge")
    return arr[:lengte]


def scoor_tijdlijn(clip: dict, gewichten: Gewichten) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Een score per meetmoment, plus de losse onderdelen voor uitleg."""
    reeks = clip["reeks"]
    tijden = np.asarray(reeks["tijden"], dtype=float)
    n = len(tijden)
    if n == 0:
        return np.zeros(0), {}

    onderdelen = {
        "beweging": _reeks(reeks, "beweging", n),
        "scherpte": _reeks(reeks, "scherpte", n),
        "belichting": _reeks(reeks, "belichting", n),
        "shake": _reeks(reeks, "shake", n),
        "vlakheid": _reeks(reeks, "vlakheid", n),
    }

    tel = clip.get("telemetrie") or {}
    gezichten = _reeks(tel, "gezichten", n)
    onderdelen["gezicht"] = np.clip(gezichten, 0, 2) / 2.0

    # Te donker: alleen straffen onder ~120 lux. Daarboven maakt meer licht
    # het beeld niet beter, dus daar hoort geen score aan te hangen.
    lux = tel.get("lux")
    if lux:
        arr = _reeks(tel, "lux", n)
        onderdelen["te_donker"] = np.clip((120.0 - arr) / 120.0, 0.0, 1.0)
    else:
        onderdelen["te_donker"] = np.zeros(n)

    # Geluid: waar het niet stil is. Dit is nadrukkelijk geen spraakdetectie -
    # wind en verkeer tellen mee. Alleen bruikbaar bij pratende koppen.
    geluid = np.zeros(n)
    audio = clip.get("audio") or {}
    if audio.get("heeft_audio"):
        geluid[:] = 1.0
        for a, b in audio.get("stiltes", []):
            geluid[(tijden >= a) & (tijden < b)] = 0.0
    onderdelen["geluid"] = geluid

    score = np.zeros(n)
    for naam, gewicht in gewichten.signalen().items():
        if gewicht and naam in onderdelen:
            score += gewicht * onderdelen[naam]

    return score, onderdelen


def _venster_scores(
    tijden: np.ndarray, score: np.ndarray, lengte: float, gewichten: Gewichten
) -> list[tuple[float, float, float]]:
    """Score van elk venster van `lengte` seconden.

    Niet simpelweg het gemiddelde. Twee correcties, allebei uit meting:

    1. Een venster telt mee voor `consistentie` deel op zijn *slechtste*
       moment. Een segment dat gemiddeld mooi is maar halverwege wegzakt in
       onscherpte is in de montage onbruikbaar.
    2. Een lengtebonus, anders wint het kortste venster altijd - middelen
       over meer tijd verdunt de piek nu eenmaal.
    """
    if len(tijden) < 2:
        return []
    stap = float(np.median(np.diff(tijden))) or 0.25
    breedte = max(2, int(round(lengte / stap)))
    if breedte >= len(score):
        return []

    # Voortschrijdend gemiddelde via cumulatieve som: O(n) in plaats van O(n*w).
    cum = np.concatenate([[0.0], np.cumsum(score)])
    gem = (cum[breedte:] - cum[:-breedte]) / breedte

    # Voortschrijdend minimum.
    vensters = np.lib.stride_tricks.sliding_window_view(score, breedte)
    minimum = vensters.min(axis=1)[: len(gem)]

    c = gewichten.consistentie
    gecombineerd = (1.0 - c) * gem + c * minimum
    bonus = gewichten.lengte_voorkeur * float(np.log2(lengte / VENSTERS[0] + 1.0))

    uit: list[tuple[float, float, float]] = []
    for i, waarde in enumerate(gecombineerd):
        start = float(tijden[i])
        eind = start + lengte
        if eind <= tijden[-1] + 1e-6:
            uit.append((start, eind, float(waarde) + bonus))
    return uit


def kandidaten(
    clip: dict,
    gewichten: Gewichten,
    *,
    vensters: tuple[float, ...] = VENSTERS,
    maximaal: int = 6,
    min_afstand: float = MIN_AFSTAND,
) -> list[Segment]:
    """De beste, elkaar niet overlappende stukken uit een clip."""
    score, onderdelen = scoor_tijdlijn(clip, gewichten)
    if len(score) == 0:
        return []
    tijden = np.asarray(clip["reeks"]["tijden"], dtype=float)
    hashes = clip["reeks"].get("hashes") or []

    alle: list[tuple[float, float, float]] = []
    for lengte in vensters:
        if lengte > clip["duur"]:
            continue
        alle.extend(_venster_scores(tijden, score, lengte, gewichten))

    if not alle:
        # Clip korter dan het kortste venster: neem hem in zijn geheel.
        alle = [(0.0, clip["duur"], float(score.mean()))]

    alle.sort(key=lambda x: x[2], reverse=True)

    gekozen: list[Segment] = []
    for start, eind, waarde in alle:
        if len(gekozen) >= maximaal:
            break
        botst = any(
            not (eind + min_afstand <= g.start or start >= g.eind + min_afstand) for g in gekozen
        )
        if botst:
            continue

        masker = (tijden >= start) & (tijden < eind)
        detail = {
            naam: round(float(arr[masker].mean()), 3) for naam, arr in onderdelen.items() if masker.any()
        }
        midden = int(np.argmin(np.abs(tijden - (start + eind) / 2)))
        gekozen.append(
            Segment(
                clip=clip["id"],
                scene=int(clip.get("scene", 0)),
                start=round(start, 3),
                eind=round(eind, 3),
                score=round(waarde, 4),
                onderdelen=detail,
                hash=int(hashes[midden]) if midden < len(hashes) else 0,
            )
        )

    gekozen.sort(key=lambda s: s.start)
    return gekozen


def alle_kandidaten(analyse: dict, gewichten: Gewichten, *, per_clip: int = 6) -> list[Segment]:
    uit: list[Segment] = []
    for clip in analyse["clips"]:
        uit.extend(kandidaten(clip, gewichten, maximaal=per_clip))
    uit.sort(key=lambda s: s.score, reverse=True)
    return uit


def ontdubbel(segmenten: list[Segment], *, drempel: float = 0.88) -> list[Segment]:
    """Gooi segmenten weg die er bijna identiek uitzien als een beter segment."""
    from .beeld import gelijkenis

    gehouden: list[Segment] = []
    for s in segmenten:
        if s.hash and any(gelijkenis(s.hash, g.hash) >= drempel for g in gehouden if g.hash):
            continue
        gehouden.append(s)
    return gehouden


def laad_gewichten(stijl: str, styles_map: Path) -> Gewichten:
    """Verouderd. Gebruik `cve.stijl.laad(...).gewichten`."""
    from ..stijl import laad

    return Gewichten(**laad(stijl, styles_map).gewichten.__dict__)
