"""Hoe lang duurt het nog? Gemeten in seconden bronvideo per seconde wandklok.

**Waarom niet op aantal bestanden.** Eén clip van vier minuten kost net zoveel
tijd als twaalf van twintig seconden. Een balk die bestanden telt loopt daarom
met sprongen en belooft onzin: bij "3 van 21" kan negentig procent van het werk
al gedaan zijn, of tien procent. De eenheid waarin dit werk écht gemeten wordt
is seconden bronvideo.

**Waarom per fase een eigen tarief.** Inlezen zet 4K-video om naar een proxy;
analyseren leest die proxy met OpenCV. Op dezelfde seconde bronvideo is dat
ruim een factor tien verschil. Eén gemiddeld tarief over beide fasen zou
tijdens het inlezen veel te optimistisch zijn en tijdens het analyseren veel
te somber.

**Waarom bewaard per machine.** De eerste keer kan er geen eerlijk getal staan
— er is nog niets gemeten, en dan staat er "schatten…". De tweede keer wel,
want dan weet déze machine wat hij kan. Een startwaarde van een andere machine
is een gok en telt daarom niet als meting.

**Waarom additief.** Wie tijdens het verwerken nog clips toevoegt, maakt de
klus groter. `plan()` en `klus()` tellen erbij op in plaats van te overschrijven,
zodat de schatting meegroeit in plaats van terug naar nul te springen.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import paths

# Waar het ijkpunt komt te liggen: na zoveel boekingen. Zes, omdat de analyse
# zes processen gebruikt en het inlezen vier draden: clips komen in golven uit
# zo'n pool, en een ijkpunt midden in de eerste golf meet die golf en niet de
# machine. Onder deze grens, of korter dan MIN_WANDKLOK, geldt wat deze machine
# eerder haalde — en staat er anders "schatten…".
MIN_PUNTEN = 6
MIN_WANDKLOK = 1.5

# Over hoeveel boekingen ná het ijkpunt het tarief van deze run dat van de
# vorige verdringt. Twaalf is ruim twee golven: op 63 clips sprong "nog ±" van
# 30 naar 44 seconden doordat een meting van één golf breed het overnam
# (gemeten 04-10-2026).
OVERGANG = 12

# Startwaarden in bron-seconden per wandkloksecond, gemeten 04-10-2026 op de
# M4 Pro met de 21 testclips (342 s 4K60, verse proxies): inlezen 26 s,
# analyseren 7,5 s, afronden 2,9 s. Ze dienen om een fase die nog niet begonnen
# is mee te kunnen rekenen; voor de eerste fase van een run gelden ze niet —
# daar staat "schatten…" tot er echt gemeten is, zie `resterend()`.
AANNAME: dict[str, float] = {"inlezen": 13.0, "analyseren": 45.0, "afronden": 190.0}

BESTAND = "doorvoer.json"

# Een tarief bewaren mag alleen na een fase die er echt iets van zegt. Twee
# clips van drie seconden zeggen niets over een machine. De eis staat vooral op
# de hoeveelheid bronvideo en niet op de wandklok: "afronden" is op de 21
# testclips maar 1,8 s, en dat is een echte meting — een klusje van 4 s
# bronvideo is dat niet, hoe lang het ook duurde.
BEWAAR_WANDKLOK = 1.0
BEWAAR_BRON = 60.0


def _bestand() -> Path:
    return paths.steun_map() / BESTAND


def lees_tarieven() -> dict[str, float]:
    """Wat deze machine eerder haalde, per fase. Leeg als er niets staat."""
    try:
        ruw = json.loads(_bestand().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(ruw, dict):
        return {}
    uit = {}
    for naam, waarde in ruw.items():
        if isinstance(waarde, (int, float)) and waarde > 0:
            uit[str(naam)] = float(waarde)
    return uit


def _schrijf_tarieven(nieuw: dict[str, float]) -> None:
    pad = _bestand()
    samen = {**lees_tarieven(), **nieuw}
    try:
        pad.parent.mkdir(parents=True, exist_ok=True)
        tijdelijk = pad.with_suffix(".deel")
        tijdelijk.write_text(json.dumps(samen, indent=2) + "\n", encoding="utf-8")
        tijdelijk.replace(pad)
    except OSError:
        pass  # een schatting die niet bewaard kan worden is geen reden om te stoppen


@dataclass
class _Fase:
    """Eén fase: hoeveel bronvideo erdoor moet, en hoe snel dat tot nu toe gaat."""

    totaal: float | None = None  # None = gebruik de maat van de hele klus
    gedaan: float = 0.0
    stuks: int = 0  # hoe vaak er geboekt is — de maat voor "genoeg gemeten"
    begon: float | None = None
    # (tijd, gedaan) op het moment dat deze fase op gang was. Zie `tarief()`.
    ijk: tuple[float, float] | None = None
    #: Wandkloktijd van eerder afgeronde rondes van deze fase. Zie `plan()`.
    wand: float = 0.0
    # Wanneer er voor het laatst geboekt is. Niet "nu": `bewaar()` draait aan
    # het eind van de hele klus, en met `nu` kreeg het inlezen de tijd van de
    # analyse en het afronden erbij. Het bewaarde tarief lag daardoor een
    # derde te laag, en de tweede run voorspelde het slechter dan de eerste
    # (gemeten 04-10-2026: inlezen 9,7 bewaard tegenover 13,5 echt).
    laatst: float | None = None

    def tarief(self, tot: float) -> float | None:
        """Bron-seconden per wandkloksecond, gerekend vanaf het ijkpunt.

        **Niet vanaf het begin van de fase, en niet over een glijdend venster.
        Beide zijn gemeten en beide gaan de mist in** (04-10-2026, 21 clips):

        - *Vanaf het begin van de fase.* Een pool van vier of zes werkers heeft
          altijd evenveel clips onderhanden die nog niet geboekt zijn, plus het
          opstarten. Dat gemiddelde loopt dus structureel achter: op 36 % van de
          klus stond de balk op 27 % en beloofde 33 seconden waar er 23 te gaan
          waren.
        - *Een glijdend venster.* Dat ankert op afgeronde clips, maar die zijn
          begonnen vóórdat het venster begon — het deelt hun werk dus door een
          te korte tijd. Daardoor sprong "nog ±" bij de vijfde clip van 9 naar
          13 seconden.

        Wat overblijft is het ijkpunt: de stand op het moment dat de pool op
        gang was (`MIN_PUNTEN` boekingen). Vanaf daar meten we de doorvoer van
        een pool die draait — precies het tarief waarmee de rest van de fase
        gaat. Het opstarten is op dat moment al verleden tijd en hoort niet in
        de voorspelling van wat er nog komt.
        """
        if self.ijk is None or self.gedaan <= 0:
            return None
        t0, s0 = self.ijk
        wand, bron = tot - t0, self.gedaan - s0
        if wand < MIN_WANDKLOK or bron <= 0:
            return None
        return bron / wand


class Meter:
    """Meet de doorvoer van een klus met meerdere fasen.

    Draadveilig: ingest en analyse boeken vanuit een pool, de interface leest
    er tussendoor uit.
    """

    def __init__(self, fasen: Sequence[str]) -> None:
        if not fasen:
            raise ValueError("een meter zonder fasen meet niets")
        self._slot = threading.Lock()
        self.fasen = list(fasen)
        self._f = {n: _Fase() for n in self.fasen}
        self._klus = 0.0
        self._gestart = time.monotonic()
        self._nu = self.fasen[0]
        self._bewaard = lees_tarieven()
        # Eén keer een getal gegeven is nooit meer "schatten…". Zonder deze
        # klink sprong de tekst bij elke fasewissel terug naar "schatten…",
        # ook op driekwart van de klus: de nieuwe fase had nog geen meting.
        # Een getal dat een beetje naast zit is daar beter dan geen getal.
        self._gegeven = False
        # Een balk die achteruit gaat leest als een fout — zelfde regel als in
        # voortgang.py. Een nieuwe meting mag "nog ±" wél omhoog bijstellen.
        # De klink gaat los zodra er wérk bij komt: wie clips toevoegt heeft
        # echt meer te gaan, en dan is een volle balk met "nog 10 s" eronder
        # geen rust maar een tegenstrijdigheid.
        self._hoogste = 0.0

    @property
    def verstreken(self) -> float:
        return round(time.monotonic() - self._gestart, 1)

    @property
    def fase(self) -> str:
        with self._slot:
            return self._nu

    def klus(self, bron_seconden: float) -> None:
        """Zo veel bronvideo komt er (nog) bij in de hele klus.

        Een fase die zelf nog niets gepland heeft rekent met dit getal. Dat is
        precies wat een fase nodig heeft die nog niet begonnen is: zonder deze
        maat zou "nog ±" tijdens het inlezen het analyseren vergeten, en dus
        structureel te weinig beloven.
        """
        with self._slot:
            if bron_seconden > 0:
                self._klus += bron_seconden
                self._hoogste = 0.0

    def plan(self, fase: str, bron_seconden: float) -> None:
        """Deze fase is begonnen en moet (nog) dit aantal bron-seconden doen."""
        with self._slot:
            f = self._f.setdefault(fase, _Fase())
            if fase not in self.fasen:
                self.fasen.append(fase)
            if bron_seconden > 0:
                f.totaal = (f.totaal or 0.0) + bron_seconden
                self._hoogste = 0.0
            nu = time.monotonic()
            if f.begon is None:
                f.begon = nu
            elif f.laatst is not None and self._nu != fase:
                # Deze fase draaide eerder al, er is daarna een ándere fase
                # langs geweest, en nu begint hij opnieuw: een tweede ronde.
                # De tijd ertussen hoort niet bij déze fase — `bewaar()`
                # rekende anders de analyse en het afronden mee als inleestijd,
                # en het bewaarde tarief lag daardoor een factor te laag.
                # (Werk bijboeken aan de lópende fase is iets anders; daar
                # blijft de meting gewoon staan.)
                f.wand += f.laatst - f.begon
                f.begon = nu
                f.laatst = None
                f.ijk = None
            self._nu = fase

    def boek(self, fase: str, bron_seconden: float) -> None:
        """Er zijn zoveel seconden bronvideo door deze fase heen."""
        if bron_seconden <= 0:
            return
        with self._slot:
            f = self._f.setdefault(fase, _Fase())
            f.gedaan += bron_seconden
            f.stuks += 1
            f.laatst = time.monotonic()
            if f.stuks == MIN_PUNTEN:
                f.ijk = (f.laatst, f.gedaan)

    def _totaal(self, fase: str) -> float:
        f = self._f[fase]
        return (f.totaal if f.totaal is not None else self._klus) or 0.0

    def _gemeten(self, fase: str) -> float | None:
        """Is er een échte meting voor deze fase? Dit beslist over "schatten…".

        Deze run, en anders wat deze machine eerder haalde. Een startwaarde uit
        `AANNAME` komt van een andere machine en telt hier niet mee.
        """
        return self._f[fase].tarief(time.monotonic()) or self._bewaard.get(fase)

    def _tarief(self, fase: str) -> float | None:
        """Het tarief waarmee we rekenen: gemeten, met het vorige als houvast.

        Een meting die net begonnen is ziet nog maar een paar clips, en dat
        kunnen net de korte of net de lange zijn. Daarom weegt een jonge meting
        mee met wat er eerder gold, en hoe meer er sinds het ijkpunt geboekt
        is, hoe meer de eigen meting het overneemt.
        """
        f = self._f[fase]
        gemeten = f.tarief(time.monotonic())
        terugval = self._bewaard.get(fase) or AANNAME.get(fase)
        if gemeten is None:
            return terugval
        if terugval is None:
            return gemeten
        w = min(max(0, f.stuks - MIN_PUNTEN), OVERGANG) / OVERGANG
        return w * gemeten + (1.0 - w) * terugval

    def _werktijd(self) -> tuple[float, float] | None:
        """(gedaan, totaal) in wandkloksekonden, over alle fasen.

        Dit is de enige som in deze module; `resterend()` en `aandeel()` lezen
        er allebei uit, zodat de balk en het getal nooit uit elkaar kunnen
        lopen. Geeft None zolang er nog nooit echt gemeten is — zie
        `resterend()`.
        """
        if not self._gegeven and self._gemeten(self._nu) is None:
            return None
        # Nog niets gepland: dan is de klus nog niet opgemeten en zou een
        # bekende machine meteen "nog 0 seconden" beloven. Dat is geen
        # schatting maar een leugen; hier hoort "schatten…".
        if self._klus <= 0 and all(not self._totaal(n) for n in self.fasen):
            return None
        gedaan = totaal = 0.0
        for naam in self.fasen:
            tarief = self._tarief(naam) or AANNAME.get(naam)
            if tarief is None or tarief <= 0:
                return None
            f = self._f[naam]
            totaal += max(f.gedaan, self._totaal(naam)) / tarief
            gedaan += f.gedaan / tarief
        self._gegeven = True
        return gedaan, totaal

    def resterend(self) -> float | None:
        """Seconden te gaan, of None zolang er niets eerlijks te melden valt.

        None betekent "schatten…": voor de fase waar we nú in zitten is er geen
        meting — niet uit deze run en niet van een eerdere run op deze machine.
        Een startwaarde van een andere machine is geen meting en mag hier dus
        niet voor doorgaan. Voor fasen die nog niet begonnen zijn mag dat wel:
        die helemaal weglaten zou een grotere fout zijn dan ze ruw schatten.
        """
        with self._slot:
            werk = self._werktijd()
        if werk is None:
            return None
        gedaan, totaal = werk
        return round(max(0.0, totaal - gedaan))

    def aandeel(self) -> float | None:
        """Hoe ver de klus is, als breuk — gewogen naar tijd, niet naar bronvideo.

        Inlezen kost per seconde bronvideo ruim tien keer zoveel als analyseren.
        Een balk op bronvideo zou daarom in de eerste fase vastzitten en in de
        tweede vooruitschieten. Deze breuk komt uit dezelfde som als
        `resterend()`, dus de balk staat op 90 % precies wanneer het getal zegt
        dat er een tiende over is.
        """
        with self._slot:
            werk = self._werktijd()
            if werk is None:
                return None
            gedaan, totaal = werk
            if totaal <= 0:
                return None
            self._hoogste = max(self._hoogste, min(1.0, gedaan / totaal))
            return round(self._hoogste, 4)

    def naar_dict(self) -> dict:
        """Wat de interface nodig heeft om "verstreken" en "nog ±" te tekenen."""
        resterend = self.resterend()
        aandeel = self.aandeel()
        with self._slot:
            f = self._f[self._nu]
            totaal = self._totaal(self._nu)
        return {
            "verstreken": self.verstreken,
            "resterend": resterend,
            "aandeel": aandeel,
            "bron_gedaan": round(f.gedaan, 1),
            "bron_totaal": round(totaal, 1),
        }

    def bewaar(self) -> dict[str, float]:
        """Leg de gemeten tarieven vast voor de volgende keer.

        Alleen fasen die er echt iets over zeggen: een ronde van twee seconden
        meet niet de machine maar de ruis.
        """
        nieuw: dict[str, float] = {}
        with self._slot:
            for naam, f in self._f.items():
                if f.begon is None or f.laatst is None or f.gedaan <= 0:
                    continue
                # Over de héle fase, niet over het ijkpunt: dit is een andere
                # vraag dan "hoe snel gaat het nú". Daarom ook geen eis aan het
                # aantal boekingen — een fase als afronden boekt in één keer.
                # `f.wand` houdt eerdere rondes bij; de tijd die een ándere
                # fase daartussen kostte hoort er niet bij.
                wand = f.wand + (f.laatst - f.begon)
                if wand < BEWAAR_WANDKLOK or f.gedaan < BEWAAR_BRON:
                    continue
                nieuw[naam] = round(f.gedaan / wand, 3)
        if nieuw:
            _schrijf_tarieven(nieuw)
        return nieuw
