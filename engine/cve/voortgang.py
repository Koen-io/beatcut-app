"""Voortgang van langlopend werk, in gewone taal.

Renderen duurt tientallen seconden tot minuten. Een knop die grijs wordt en
verder niets zegt, voelt als vastlopen - ook als er hard gewerkt wordt. Deze
module houdt per project bij wát er gebeurt en hoe ver het is, zodat de
interface het kan laten zien.

Twee dingen die de moeite waard zijn:

**De weging is niet gelijkmatig.** Blokken renderen is het grootste deel van
het werk, nakijken het kleinste. Als elke fase evenveel procent zou krijgen,
schiet de balk in het begin vooruit en blijft hij daarna hangen - dat voelt
trager dan een balk die gelijkmatig loopt, ook al duurt het even lang.

**Alles staat in het geheugen, niets op schijf.** Voortgang is per definitie
van nu; hem bewaren zou alleen maar verouderde stand opleveren na een
herstart.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

# Elke fase krijgt een deel van de balk, naar rato van hoe lang hij duurt.
# Gemeten op een montage van 75 s uit proxies: blokken ~14 s, geluid ~2 s,
# titels ~4 s, samenstellen ~1 s, nakijken ~10 s.
RENDER_FASEN: list[tuple[str, str, float]] = [
    ("voorbereiden", "Montage klaarzetten", 0.02),
    ("blokken", "Beelden knippen", 0.46),
    ("samenstellen", "Beelden aan elkaar zetten", 0.06),
    ("geluid", "Muziek eronder en geluid op niveau", 0.10),
    ("titels", "Titels en ondertitels erover", 0.16),
    ("nakijken", "De video nakijken", 0.20),
]

# De wizard doet het hele traject in één keer. Gemeten op 21 clips van samen
# 5,7 minuten: inlezen 93 s, analyseren 8 s, monteren 1 s, renderen 20 s,
# nakijken 10 s. Inlezen is dus verreweg het zwaarst - dat is ook precies
# waar mensen ongeduldig worden, dus daar moet de balk eerlijk traag lopen.
WIZARD_FASEN: list[tuple[str, str, float]] = [
    ("inlezen", "Je beelden inlezen", 0.44),
    ("analyseren", "Kijken en luisteren naar je materiaal", 0.10),
    ("monteren", "De montage bedenken", 0.02),
    ("voorbereiden", "Montage klaarzetten", 0.01),
    ("blokken", "Beelden knippen", 0.19),
    ("samenstellen", "Beelden aan elkaar zetten", 0.03),
    ("geluid", "Muziek eronder en geluid op niveau", 0.04),
    ("titels", "Titels en ondertitels erover", 0.07),
    ("nakijken", "De video nakijken", 0.10),
]


@dataclass
class Stand:
    project: str
    bezig: bool = True
    fase: str = ""
    tekst: str = "Bezig…"
    # De faseverdeling van dít karwei. Renderen en de wizard hebben elk hun
    # eigen weging; zonder dat springt de balk bij de wizard meteen naar 40 %
    # omdat "renderen" daar maar een deel van het werk is.
    fasen: list = field(default_factory=lambda: list(RENDER_FASEN))
    klaar: int = 0
    totaal: int = 0
    percentage: float = 0.0
    # Pas gevuld als het af is:
    bestand: str = ""
    review: dict | None = None
    fout: str = ""
    gestart: float = field(default_factory=time.time)
    # Waar de balk al stond toen dit karwei begon. De wizard slaat inlezen en
    # analyseren over als die al gedaan zijn; zonder dit ijkpunt deelt de
    # schatting de verstreken tijd door een halve balk die geen tijd kostte,
    # en dan belooft hij "nog 5 seconden" terwijl er nog een minuut te gaan is.
    vanaf: float = 0.0

    @property
    def verstreken(self) -> float:
        return round(time.time() - self.gestart, 1)

    def naar_dict(self) -> dict:
        d = asdict(self)
        d.pop("fasen", None)  # interne weging, niets voor de interface
        d["verstreken"] = self.verstreken
        d["resterend"] = self.schatting()
        return d

    def plek(self, fase: str) -> tuple[float, float, str]:
        """Waar in de balk deze fase begint, hoe breed hij is, en zijn tekst."""
        op = 0.0
        for naam, tekst, gewicht in self.fasen:
            if naam == fase:
                return op, gewicht, tekst
            op += gewicht
        return op, 0.0, fase

    def schatting(self) -> float | None:
        """Ruwe schatting van de resterende tijd, in seconden.

        Puur op basis van hoe lang het tot nu toe duurde per procent. Meer
        precisie is hier niet eerlijk: de ene clip rendert nu eenmaal sneller
        dan de andere.
        """
        gedaan = self.percentage - self.vanaf
        if not self.bezig or gedaan < 3:
            return None
        per_procent = self.verstreken / gedaan
        return round(max(0.0, (100.0 - self.percentage) * per_procent), 0)


_slot = threading.Lock()
_standen: dict[str, Stand] = {}


def start(project: str, fasen: list | None = None, *, vanaf_fase: str = "") -> Stand:
    """Begin een nieuw karwei.

    `vanaf_fase` slaat alles tot en met die fase over: de balk begint daar en
    de tijdschatting rekent daar vanaf.
    """
    with _slot:
        s = Stand(project=project, fasen=list(fasen or RENDER_FASEN))
        s.tekst = s.fasen[0][1] if s.fasen else "Bezig…"
        s.fase = s.fasen[0][0] if s.fasen else ""
        if vanaf_fase:
            basis, breedte, _ = s.plek(vanaf_fase)
            s.vanaf = s.percentage = round((basis + breedte) * 100, 1)
        _standen[project] = s
        return s


def meld(project: str, fase: str, klaar: int = 0, totaal: int = 0) -> None:
    """Zeg waar we zijn. `klaar`/`totaal` mag 0 blijven als er niets te tellen is."""
    with _slot:
        s = _standen.get(project)
        if s is None:
            return
        basis, breedte, tekst = s.plek(fase)
        s.fase = fase
        s.tekst = tekst
        s.klaar, s.totaal = klaar, totaal
        aandeel = (klaar / totaal) if totaal else 0.0
        # Nooit terugspringen: een balk die achteruit gaat leest als een fout.
        s.percentage = max(s.percentage, round((basis + breedte * aandeel) * 100, 1))


def klaar(project: str, bestand: str = "", review: dict | None = None) -> None:
    with _slot:
        s = _standen.get(project)
        if s is None:
            return
        s.bezig = False
        s.fase = "klaar"
        s.tekst = "Klaar"
        s.percentage = 100.0
        s.bestand = bestand
        s.review = review


def mislukt(project: str, fout: str) -> None:
    with _slot:
        s = _standen.get(project)
        if s is None:
            return
        s.bezig = False
        s.fase = "fout"
        s.tekst = "Er ging iets mis"
        s.fout = fout


def stand(project: str) -> dict | None:
    with _slot:
        s = _standen.get(project)
        return s.naar_dict() if s else None


def wis(project: str) -> None:
    with _slot:
        _standen.pop(project, None)
