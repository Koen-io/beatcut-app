"""Beeldstijlen: wat een goed shot is, los van het snijritme.

Een stijl zegt sinds 03-10-2026 niets meer over het tempo. Dat komt uit de
montagestijl (`styles/montage/<id>.md`, zie `montagestijl.py`). Wat hier staat
gaat over de **beeldkeuze**:

  gewichten   welke beeldsignalen meetellen bij het kiezen van shots
  beweging    wanneer een stilstaand shot vanzelf Ken Burns krijgt
  kleur       de grade die over de hele montage gaat

In het `ritme`-blok zijn daar nog twee dingen van over:

  min_shot    de shotlengte van de terugval zonder muziek, want zonder tellen
              is er geen snijpatroon om over te stappen
  drops       of de energie van een drop uit de beeldkeuze moet komen

Alles staat als yaml-blok in `styles/<naam>.md`, met daaromheen uitleg in
gewone taal. Dat bestand is bedoeld om met de hand aan te passen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Ritme:
    """Wat er van het oude ritme-blok over is.

    Het snijtempo komt uit de montagestijl. Twee velden zijn de uitzondering:
    `min_shot` is de terugval als er geen muziek ligt, en `drops` bepaalt hoe
    de drop gevuld wordt. Per veld staat eronder wat het wel en niet doet,
    want dat is na de splitsing van 03-10-2026 niet meer te raden.
    """

    # Shotlengte van de terugval zonder muziek (`director/preset.py::_raster`).
    min_shot: float = 1.0
    # Niet door de regisseur gelezen; alleen `studio.py` geeft het door aan de
    # Studio-interface, als informatie over de stijl.
    max_shot: float = 4.0
    # Waar de energie van een drop uit komt:
    #   beeld    een flinke bonus op de beeldscore, zodat de sterkste shots in
    #            de drop terechtkomen
    #   sneller  alleen een kleine bonus op beweging; het tempo zelf staat in
    #            de montagestijl en verandert hier niet van
    drops: str = "sneller"
    # Bedoeld om openings- en slotshot langer te laten duren dan de rest, maar
    # nooit gebouwd: niets leest deze twee, al sinds 0.1.0. Zie brein-taak
    # 20261004-031546 — weghalen is een eigen besluit, niet dat van deze opruiming.
    opening_extra: float = 0.0
    slot_extra: float = 0.0


@dataclass
class Gewichten:
    """Zie `analyze/segmenten.py` voor wat elk signaal betekent."""

    beweging: float = 0.30
    scherpte: float = 0.25
    belichting: float = 0.15
    shake: float = -0.10
    vlakheid: float = -0.15
    gezicht: float = 0.15
    te_donker: float = -0.30
    geluid: float = 0.0
    lengte_voorkeur: float = 0.06
    consistentie: float = 0.35

    def signalen(self) -> dict[str, float]:
        uit = dict(self.__dict__)
        uit.pop("lengte_voorkeur", None)
        uit.pop("consistentie", None)
        return uit


@dataclass
class Beweging:
    """Wanneer een shot dat stilstaat vanzelf Ken Burns krijgt.

    Een statief-shot van vier seconden is op zichzelf niets mis mee, maar in
    een montage voelt het als een bevroren beeld: het oog heeft niets te doen.
    Een trage duw van tien procent lost dat op zonder dat iemand doorheeft dat
    er iets gebeurt.

    Waarom dit per stijl instelbaar is: bij landschap is dit precies de
    bedoeling, bij actie zijn de shots zo kort dat een beweging alleen maar
    onrust toevoegt.
    """

    ken_burns: bool = True
    # Bewegingsscore (0..1, zie analyze/segmenten.py) waaronder een shot als
    # stilstaand telt. Gemeten: een statief-shot zit rond 0.02, een
    # handheld-wandeling rond 0.55.
    drempel: float = 0.12
    # Korter dan dit valt een langzame beweging toch niet op, en dan kost het
    # alleen maar scherpte.
    min_duur: float = 1.5
    kracht: float = 0.10  # bij precies de drempel
    kracht_max: float = 0.18  # bij een volledig stilstaand shot


@dataclass
class Stijl:
    naam: str
    titel: str = ""
    omschrijving: str = ""
    gewichten: Gewichten = field(default_factory=Gewichten)
    ritme: Ritme = field(default_factory=Ritme)
    beweging: Beweging = field(default_factory=Beweging)
    grade: dict[str, float] = field(default_factory=dict)
    # Wat uit jouw keuzes geleerd is, apart gehouden van wat in het
    # stijlbestand staat. `gewichten` is de som van beide; deze twee velden
    # zijn er zodat je altijd kunt zien wélk deel waar vandaan komt.
    basis: Gewichten = field(default_factory=Gewichten)
    bijstelling: dict[str, float] = field(default_factory=dict)


def _yaml_blokken(tekst: str) -> dict[str, dict[str, str]]:
    """Haal de yaml-blokken uit een markdownbestand, op naam.

    Een blok begint met ```yaml <naam> en loopt tot de volgende ```.
    Bewust geen yaml-bibliotheek: we hebben alleen sleutel-waardeparen nodig
    en dat scheelt een afhankelijkheid in de installer.
    """
    uit: dict[str, dict[str, str]] = {}
    huidig: str | None = None
    for regel in tekst.splitlines():
        gestript = regel.strip()
        if gestript.startswith("```"):
            if huidig is None and "yaml" in gestript:
                naam = gestript.replace("```yaml", "").strip() or "gewichten"
                huidig = naam
                uit.setdefault(huidig, {})
            else:
                huidig = None
            continue
        if huidig is None or ":" not in gestript or gestript.startswith("#"):
            continue
        sleutel, _, rest = gestript.partition(":")
        waarde = rest.split("#")[0].strip()
        if waarde:
            uit[huidig][sleutel.strip()] = waarde
    return uit


def _kop(tekst: str) -> tuple[str, str]:
    """Titel en eerste alinea uit het markdownbestand."""
    regels = [r.strip() for r in tekst.splitlines()]
    titel = ""
    omschrijving = ""
    for i, r in enumerate(regels):
        if r.startswith("# "):
            titel = r[2:].strip()
            for volgende in regels[i + 1 :]:
                if volgende and not volgende.startswith("#"):
                    omschrijving = volgende
                    break
            break
    return titel, omschrijving


def _getal(d: dict[str, str], sleutel: str, standaard: float) -> float:
    try:
        return float(d.get(sleutel, standaard))
    except (TypeError, ValueError):
        return standaard


def _met_bijstelling(basis: Gewichten, bijstelling: dict[str, float]) -> Gewichten:
    """Tel het geleerde bij de gewichten uit het stijlbestand op.

    Alleen signalen die in `Gewichten` bestaan; een oud geleerd bestand met
    een signaal dat de engine niet meer kent, mag geen fout opleveren.
    """
    uit = Gewichten(**basis.__dict__)
    for signaal, d in (bijstelling or {}).items():
        if hasattr(uit, signaal):
            setattr(uit, signaal, round(getattr(uit, signaal) + float(d), 4))
    return uit


def laad(naam: str, styles_map: Path, *, met_geheugen: bool = True) -> Stijl:
    pad = styles_map / f"{naam}.md"
    if not pad.exists():
        return Stijl(naam=naam, titel=naam.capitalize())

    tekst = pad.read_text(encoding="utf-8")
    blokken = _yaml_blokken(tekst)
    titel, omschrijving = _kop(tekst)

    g = blokken.get("gewichten", {})
    gewichten = Gewichten(
        **{
            k: _getal(g, k, v)
            for k, v in Gewichten().__dict__.items()
        }
    )

    r = blokken.get("ritme", {})
    standaard = Ritme()
    ritme = Ritme(
        min_shot=_getal(r, "min_shot", standaard.min_shot),
        max_shot=_getal(r, "max_shot", standaard.max_shot),
        drops=r.get("drops", standaard.drops),
        opening_extra=_getal(r, "opening_extra", standaard.opening_extra),
        slot_extra=_getal(r, "slot_extra", standaard.slot_extra),
    )

    bw = blokken.get("beweging", {})
    standaard_bw = Beweging()
    beweging = Beweging(
        ken_burns=str(bw.get("ken_burns", "ja")).lower() not in ("nee", "false", "0", "uit"),
        drempel=_getal(bw, "drempel", standaard_bw.drempel),
        min_duur=_getal(bw, "min_duur", standaard_bw.min_duur),
        kracht=_getal(bw, "kracht", standaard_bw.kracht),
        kracht_max=_getal(bw, "kracht_max", standaard_bw.kracht_max),
    )

    kl = blokken.get("kleur", {})
    grade = {k: _getal(kl, k, 1.0 if k in ("contrast", "verzadiging") else 0.0) for k in kl}

    bijstelling: dict[str, float] = {}
    if met_geheugen:
        # Laat importeren: `geheugen` gebruikt `paths`, en zo blijft `stijl`
        # bruikbaar in een omgeving zonder projectmappen.
        from .geheugen import laad_geleerd

        bijstelling = laad_geleerd(naam).get("bijstelling", {}) or {}

    return Stijl(
        naam=naam,
        titel=titel or naam.capitalize(),
        omschrijving=omschrijving,
        gewichten=_met_bijstelling(gewichten, bijstelling),
        ritme=ritme,
        beweging=beweging,
        grade=grade,
        basis=gewichten,
        bijstelling=bijstelling,
    )


def alle(styles_map: Path) -> list[Stijl]:
    return [laad(p.stem, styles_map) for p in sorted(styles_map.glob("*.md"))]
