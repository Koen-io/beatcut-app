"""Montagestijlen: het ritme van de montage, los van het soort beelden.

"Stijl" was tot nu toe één ding. Dat zijn er sinds 03-10-2026 twee, precies
zoals PLAN-v2.md §4 het beschrijft:

  **soort beelden** (`styles/<naam>.md`, vijf stuks)
      Wat een góed shot is: welke beeldsignalen meetellen bij het kiezen.
      Wordt herkend uit het materiaal (`stijlkeuze.py`), dus de gebruiker
      hoeft er niets van te weten.

  **montagestijl** (`styles/montage/<id>.md`, veertien stuks)
      Hoe er gesneden wordt: snijpatroon in tellen, welke overgangen mogen,
      snelheid, Ken Burns, bevriezen. Dit is wat de gebruiker in stap 2 kiest.

De twee staan los van elkaar: een reisvideo kan op Velocity en een actiefilm
op Stilte. Dat is het hele punt van de splitsing.

`patroon` staat in **tellen** en niet in maten. Vier tellen is een maat, maar
de snelle stijlen snijden binnen de maat en dan is een maat geen bruikbare
eenheid meer. De regisseur stapt over het tel-raster uit `analysis.json`, dus
elke snede valt per definitie op een tel.

Wat de renderer vandaag niet kan (whip-pan, glitch, RGB-split, een speed-ramp
binnen één shot) staat *niet* in deze bestanden. Elk stijlbestand heeft een kop
"Wat de renderer hier nog niet kan" waarin staat waarmee het benaderd is; de
lijst staat ook in PLAN-v2.md §9. Geen nep-effecten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .edl import OVERGANGEN
from .stijl import _getal, _kop, _yaml_blokken

# De overgangen die de ffmpeg-keten van `render.py` echt kan. De rest van
# `edl.OVERGANGEN` wacht op de compositor; een stijlbestand dat er een noemt
# krijgt een snede en een waarschuwing, geen stille terugval.
KAN_RENDEREN = ("snede", "crossfade", "dip_zwart", "dip_wit")


def kan_renderen() -> tuple[str, ...]:
    """Welke overgangen de export echt maakt.

    Met de compositor alle veertien (dezelfde shader als de speler); zonder
    alleen wat de oude ffmpeg-keten kan.
    """
    from . import compositor
    from .edl import OVERGANGEN

    return tuple(OVERGANGEN) if compositor.aan() else KAN_RENDEREN

# Vaste volgorde: snel naar rustig, zoals PLAN-v2.md §4.1. Alfabetisch zou
# Ambient bovenaan zetten en dat is precies de rustigste stijl die er is.
ORDE = (
    "velocity", "hype", "glitch", "fpv", "flits", "broll", "sport",
    "vlog", "cine", "docu", "retro", "verhaal", "stilte", "ambient",
)

# Welke energieniveaus onder welk filter in de interface vallen. Uit het
# ontwerp (ontwerp/beatcut2/Main.dc.html, `eBand`).
BANDEN = {
    "alles": (1, 5),
    "snel": (4, 5),
    "gemiddeld": (3, 3),
    "rustig": (1, 2),
}

# Welke montagestijl standaard bij welk soort beelden hoort. De gebruiker mag
# het met één klik overrulen; dit is alleen het vertrekpunt.
STANDAARD_BIJ = {
    "actie": "hype",
    "reis": "cine",
    "landschap": "ambient",
    "luchtvaart": "cine",
    "vlog": "vlog",
}
STANDAARD = "cine"


@dataclass
class Montagestijl:
    id: str
    titel: str = ""
    omschrijving: str = ""
    energie: int = 3
    # Shotlengtes in tellen, als cyclus. [1, 2, 2, 1] betekent: shot 1 duurt
    # één tel, shot 2 en 3 twee tellen, shot 4 één tel, en dan weer vooraan.
    patroon: list[float] = field(default_factory=lambda: [4.0])
    # Toegestane overgangen. De eerste is de gewone; een tweede wordt elke
    # `overgang_elke` snedes gebruikt.
    overgangen: list[str] = field(default_factory=lambda: ["snede"])
    overgang_elke: int = 0
    overgang_duur: float = 0.0
    ken_burns: bool = True
    # 0 = laat het soort beelden de kracht bepalen (`stijl.Beweging`).
    ken_burns_kracht: float = 0.0
    # Bewegingsscore waaronder een shot als "staat stil" telt. 0 = de drempel
    # van het soort beelden (0,12). Een rustige montagestijl zet hem hoger:
    # bij shots van vier maten valt ook een licht bewegend beeld stil.
    ken_burns_drempel: float = 0.0
    snelheid: float = 1.0
    snelheid_bij: str = "geen"  # geen | altijd | hoog | rustig
    bevriezen: float = 0.0
    bevriezen_bij: str = "geen"  # geen | altijd | hoog | rustig
    # Speed-ramp binnen één shot: snelheden op gelijke afstanden, lineair
    # ertussen. "1.0 0.35 2.2" = normaal → slow-motion → versnellen.
    ramp: list[float] = field(default_factory=list)
    ramp_bij: str = "geen"  # geen | altijd | hoog | rustig
    waarschuwingen: list[str] = field(default_factory=list)

    @property
    def gemiddeld(self) -> float:
        """Gemiddelde shotlengte in tellen."""
        return sum(self.patroon) / len(self.patroon) if self.patroon else 4.0

    @property
    def snijritme(self) -> str:
        """Het label onder de energiebalkjes. Zelfde formule als het ontwerp."""
        g = self.gemiddeld
        if g <= 1:
            return "elke tel"
        if g < 4:
            return f"≈ {g:.1f} tellen".replace(".", ",")
        if g < 8:
            return "per maat"
        return f"per {round(g / 4)} maten"

    def tellen(self, index: int) -> float:
        """Hoeveel tellen het shot met dit nummer (0-gebaseerd) duurt."""
        if not self.patroon:
            return 4.0
        return self.patroon[index % len(self.patroon)]

    def geldt(self, veld: str, niveau: str) -> bool:
        """Geldt `snelheid_bij` / `bevriezen_bij` / `ramp_bij` op dit energieniveau?"""
        wanneer = getattr(self, veld)
        return wanneer == "altijd" or wanneer == niveau

    def verloop(self) -> list[dict[str, float]]:
        """`ramp` als `snelheid_verloop` voor een VideoBlok."""
        if len(self.ramp) < 2:
            return []
        n = len(self.ramp) - 1
        return [{"t": round(i / n, 4), "snelheid": v} for i, v in enumerate(self.ramp)]

    def overgang_voor(self, index: int) -> tuple[str, float]:
        """Soort en duur van de overgang vóór shot `index` (1-gebaseerd).

        De eerste naam in `overgangen` is de gewone; de rest zijn de bijzondere,
        die elke `overgang_elke` snedes om de beurt aan bod komen.
        """
        gewoon = self.overgangen[0] if self.overgangen else "snede"
        bijzonder = self.overgangen[1:]
        if bijzonder and self.overgang_elke > 0 and index % self.overgang_elke == 0:
            keer = index // self.overgang_elke - 1
            return bijzonder[keer % len(bijzonder)], self.overgang_duur
        if gewoon == "snede":
            return "snede", 0.0
        return gewoon, self.overgang_duur

    def naar_dict(self) -> dict:
        return {
            "id": self.id,
            "titel": self.titel,
            "energie": self.energie,
            "omschrijving": self.omschrijving,
            "snijritme": self.snijritme,
            "tellen": round(self.gemiddeld, 2),
        }


def _lijst(d: dict[str, str], sleutel: str) -> list[str]:
    return [w for w in str(d.get(sleutel, "")).replace(",", " ").split() if w]


def laad(id_: str, styles_map: Path) -> Montagestijl:
    pad = styles_map / "montage" / f"{id_}.md"
    if not pad.exists():
        return Montagestijl(id=id_, titel=id_.capitalize())

    tekst = pad.read_text(encoding="utf-8")
    m = _yaml_blokken(tekst).get("montage", {})
    titel, omschrijving = _kop(tekst)

    patroon = [float(x) for x in _lijst(m, "patroon") if float(x) > 0] or [4.0]

    waarschuwingen: list[str] = []
    overgangen: list[str] = []
    for naam in _lijst(m, "overgangen") or ["snede"]:
        if naam not in OVERGANGEN:
            waarschuwingen.append(f"{id_}: overgang '{naam}' bestaat niet; snede gebruikt.")
            naam = "snede"
        elif naam not in kan_renderen():
            waarschuwingen.append(
                f"{id_}: overgang '{naam}' komt met de compositor; snede gebruikt."
            )
            naam = "snede"
        overgangen.append(naam)

    return Montagestijl(
        id=id_,
        titel=titel or id_.capitalize(),
        omschrijving=omschrijving,
        energie=max(1, min(5, int(_getal(m, "energie", 3)))),
        patroon=patroon,
        overgangen=overgangen,
        overgang_elke=int(_getal(m, "overgang_elke", 0)),
        overgang_duur=_getal(m, "overgang_duur", 0.0),
        ken_burns=str(m.get("ken_burns", "ja")).lower() not in ("nee", "false", "0", "uit"),
        ken_burns_kracht=_getal(m, "ken_burns_kracht", 0.0),
        ken_burns_drempel=_getal(m, "ken_burns_drempel", 0.0),
        snelheid=max(0.1, _getal(m, "snelheid", 1.0)),
        snelheid_bij=str(m.get("snelheid_bij", "geen")),
        bevriezen=max(0.0, _getal(m, "bevriezen", 0.0)),
        bevriezen_bij=str(m.get("bevriezen_bij", "geen")),
        ramp=[min(4.0, max(0.1, float(x))) for x in _lijst(m, "ramp")],
        ramp_bij=str(m.get("ramp_bij", "geen")),
        waarschuwingen=waarschuwingen,
    )


def alle(styles_map: Path) -> list[Montagestijl]:
    """Alle montagestijlen, van snel naar rustig."""
    map_ = styles_map / "montage"
    namen = [p.stem for p in map_.glob("*.md")] if map_.exists() else []
    op_orde = [n for n in ORDE if n in namen] + sorted(n for n in namen if n not in ORDE)
    return [laad(n, styles_map) for n in op_orde]


def standaard_bij(soort: str) -> str:
    """Welke montagestijl hoort standaard bij dit soort beelden."""
    return STANDAARD_BIJ.get(soort, STANDAARD)
