"""De regie-stap, als interface.

Dit is het punt waar smaak binnenkomt. Bewust pluggable, want de werk-editie
moet volledig offline kunnen draaien:

    preset.py       regels + scores, geen model      standaard
    lokaal.py       lokaal LLM via Ollama            later
    claude.py       Claude API met zakelijke sleutel  later

De rest van de engine praat alleen met deze interface en weet niet welke
implementatie eronder zit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..edl import EDL


@dataclass
class Brief:
    """Wat de gebruiker wil. Alles optioneel; lege brief is een geldige brief."""

    tekst: str = ""
    doelduur: float | None = None  # seconden; None = laat de muziek bepalen
    # Soort beelden: wat een goed shot is (styles/<naam>.md). Wordt herkend
    # uit het materiaal; de gebruiker hoeft er niets van te weten.
    stijl: str = "actie"
    # Montagestijl: het snijritme (styles/montage/<id>.md). Leeg betekent "kies
    # er een die bij het soort beelden past" - zie montagestijl.standaard_bij.
    montage: str = ""
    merk: str = "prive"
    vorm: str = "16:9"  # 16:9 | 9:16 | 1:1
    muziek_start: float = 0.0
    # Motion graphics. Leeg laten betekent geen titelkaart.
    titel: str = ""
    eyebrow: str = ""
    ondertitel: str = ""
    slottekst: str = ""
    # Clips of momenten die er sowieso in moeten (uit het highlight-penseel).
    vastgezet: list[dict] = field(default_factory=list)
    # Clips die er niet in mogen.
    uitgesloten: list[str] = field(default_factory=list)
    # Clip-id's die er van de gebruiker in móeten ("moet erin" uit stap 4).
    # Geen harde eis maar een flinke bonus bij de keuze: een clip waarvan geen
    # enkel stuk lang genoeg is voor dit ritme kan nergens passen, en dan is
    # een montage met een gat erger dan een clip die niet terugkomt.
    voorkeur: list[str] = field(default_factory=list)


@dataclass
class Voorstel:
    """Het antwoord van een regisseur: een EDL plus uitleg."""

    edl: EDL
    uitleg: str = ""
    waarschuwingen: list[str] = field(default_factory=list)


class Regisseur(ABC):
    """Basisklasse. Een implementatie hoeft alleen `stel_voor` te leveren."""

    naam: str = "onbekend"
    heeft_model: bool = False

    @abstractmethod
    def stel_voor(self, analyse: dict, brief: Brief) -> Voorstel:
        """Zet analyse + brief om in een EDL."""

    def herzie(self, analyse: dict, brief: Brief, huidig: EDL, opmerking: str) -> Voorstel:
        """Pas een bestaande EDL aan op basis van commentaar.

        De standaardimplementatie maakt gewoon een nieuw voorstel, maar houdt
        alles vast wat de gebruiker heeft vastgezet.
        """
        vastgezet = [
            {"clip": b.clip, "bron_start": b.bron_start, "duur": b.duur}
            for b in huidig.video
            if b.vast
        ]
        nieuwe_brief = Brief(
            tekst=(brief.tekst + "\n" + opmerking).strip(),
            doelduur=brief.doelduur,
            stijl=brief.stijl,
            montage=brief.montage,
            merk=brief.merk,
            vorm=brief.vorm,
            muziek_start=brief.muziek_start,
            vastgezet=vastgezet or brief.vastgezet,
            uitgesloten=brief.uitgesloten,
            voorkeur=brief.voorkeur,
            titel=brief.titel,
            eyebrow=brief.eyebrow,
            ondertitel=brief.ondertitel,
            slottekst=brief.slottekst,
        )
        return self.stel_voor(analyse, nieuwe_brief)


def kies_regisseur(naam: str = "preset") -> Regisseur:
    """Fabriek. Onbekende naam valt terug op preset in plaats van te falen."""
    if naam in ("preset", "regels", "geen-ai"):
        from .preset import PresetRegisseur

        return PresetRegisseur()
    from .preset import PresetRegisseur

    return PresetRegisseur()
