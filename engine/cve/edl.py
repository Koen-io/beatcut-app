"""De EDL - Edit Decision List.

Dit bestand is de enige waarheid van het project. Chat schrijft erin, de GUI
schrijft erin, de renderer leest hem. Niets anders houdt staat bij.

Belangrijk: tijden in `bron_start` verwijzen naar het **oorspronkelijke**
bestand, niet naar de proxy. Zo kan de eindrender op volledige kwaliteit,
terwijl analyse en preview op de proxy draaien.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSIE = 2

# De namen die een overgang mag hebben. Vaste lijst, want de compositor kiest
# hierop zijn shader; een typefout mag geen stille terugval op "snede" worden.
OVERGANGEN = (
    "snede",
    "crossfade",
    "dip_zwart",
    "dip_wit",
    "glitch",
    "pixel",
    "slice",
    "whip_pan",
    "zoom_punch",
    "wipe",
    "radiaal",
    "film_brand",
    "lichtlek",
    "rgb_split",
)


class EDLFout(ValueError):
    pass


# In hoeveel stukken met constante snelheid een speed-ramp wordt gerenderd.
# 24 is bij een shot van twee seconden één stap per 2,5 frame: vloeiend genoeg
# dat je geen trap ziet, en klein genoeg voor één ffmpeg-expressie.
RAMP_STUKKEN = 24


def snelheid_op(verloop: list[dict[str, float]], f: float) -> float:
    """Snelheid op fractie `f` (0..1) van een lineair verloop."""
    punten = sorted((float(p["t"]), float(p["snelheid"])) for p in verloop)
    if f <= punten[0][0]:
        return punten[0][1]
    for (t0, v0), (t1, v1) in zip(punten, punten[1:]):
        if f <= t1:
            return v0 if t1 <= t0 else v0 + (v1 - v0) * (f - t0) / (t1 - t0)
    return punten[-1][1]


def gemiddelde_snelheid(verloop: list[dict[str, float]]) -> float:
    """Bron per tijdlijnseconde, met dezelfde stukken als de renderer."""
    return sum(snelheid_op(verloop, (k + 0.5) / RAMP_STUKKEN)
               for k in range(RAMP_STUKKEN)) / RAMP_STUKKEN


@dataclass
class Canvas:
    breedte: int = 1920
    hoogte: int = 1080
    fps: int = 30

    @property
    def verhouding(self) -> float:
        return self.breedte / self.hoogte


@dataclass
class Overgang:
    soort: str = "snede"  # een naam uit OVERGANGEN
    duur: float = 0.0


@dataclass
class VideoBlok:
    """Een stuk van een bronclip op de tijdlijn."""

    id: str
    clip: str  # verwijst naar analysis.json clips[].id
    bestand: str  # bestandsnaam in bronnen/
    bron_start: float  # seconden in het oorspronkelijke bestand
    duur: float
    tijdlijn_start: float
    snelheid: float = 1.0
    # Speed-ramp (§4.1 noemt 1,0->0,3->2,5x). Lijst van {"t": fractie 0..1 van
    # de blokduur, "snelheid": factor}. Leeg = `snelheid` geldt als constante.
    snelheid_verloop: list[dict[str, float]] = field(default_factory=list)
    # Exact aantal frames. Wordt gezet door EDL.op_framerooster() en is voor de
    # renderer leidend boven `duur` - alleen zo blijven de blokken naadloos.
    frames: int = 0
    vulmodus: str = "vul"  # vul (crop) | pas (letterbox) | wazig (blurred bars)
    # Herkaderen: waar het venster in de bron valt bij vulmodus `vul`. Leeg is
    # het midden, dus een oude edl.json zonder dit veld blijft precies wat hij
    # was. Twee vormen:
    #   {"x": 0.35, "y": 0.5}                       één vast punt
    #   {"punten": [{"t": 0.0, "x": .., "y": ..}]}  keyframes over de duur
    # De wiskunde staat in `cve/kader.py`, en in dezelfde vorm in
    # `app/src/speler/uniforms.ts`.
    kader: dict[str, Any] = field(default_factory=dict)

    # -- beweging in het beeld ---------------------------------------------
    # Ken Burns: langzaam in- of uitzoomen zodat een statisch shot toch leeft.
    # "geen" | "in" | "uit" | "links" | "rechts" | "omhoog" | "omlaag"
    zoom: str = "geen"
    zoom_kracht: float = 0.12  # 0.12 = 12 % over de hele duur

    # Bevriest het laatste frame na afloop van het bewegende deel.
    bevriezen: float = 0.0  # seconden

    # -- geluid uit de clip zelf -------------------------------------------
    # 0 = alleen muziek (standaard). Hoger mengt het clipgeluid eronder.
    geluid: float = 0.0
    # J-cut: geluid begint eerder dan het beeld. L-cut: het loopt door.
    # Beide in seconden; positief betekent meer geluid.
    geluid_voor: float = 0.0
    geluid_na: float = 0.0
    overgang_in: Overgang = field(default_factory=Overgang)
    reden: str = ""  # waarom dit blok gekozen is - leesbaar voor mens en model
    vast: bool = False  # door de gebruiker vastgezet; de regisseur laat het staan

    @property
    def tijdlijn_eind(self) -> float:
        return round(self.tijdlijn_start + self.duur, 3)

    def snelheid_stukken(self) -> list[tuple[float, float]]:
        """Het blok als reeks (uitvoerduur, snelheid) met constante snelheid.

        Een speed-ramp is een lineair verloop tussen de punten van
        `snelheid_verloop`. Renderer, regisseur en bijwerken rekenen alle drie
        met déze stukken, zodat "hoeveel bron eet dit shot" overal hetzelfde
        getal is en de tijdlijn nooit verschuift.
        """
        if not self.snelheid_verloop:
            return [(self.duur, self.snelheid)]
        stap = self.duur / RAMP_STUKKEN
        return [
            (stap, snelheid_op(self.snelheid_verloop, (k + 0.5) / RAMP_STUKKEN))
            for k in range(RAMP_STUKKEN)
        ]

    @property
    def bron_lengte(self) -> float:
        """Seconden bronmateriaal die dit blok opmaakt."""
        return sum(d * v for d, v in self.snelheid_stukken())

    @property
    def bron_eind(self) -> float:
        return round(self.bron_start + self.bron_lengte, 3)


@dataclass
class OverlayBlok:
    """Een grafisch element: titel, lower-third, watermerk, ondertitel."""

    id: str
    soort: str  # titel | lowerthird | watermerk | ondertitel | vrij
    tijdlijn_start: float
    duur: float
    inhoud: dict[str, Any] = field(default_factory=dict)
    compositie: str | None = None  # bestandsnaam in composities/
    vast: bool = False

    @property
    def tijdlijn_eind(self) -> float:
        return round(self.tijdlijn_start + self.duur, 3)


@dataclass
class AudioSpoor:
    bestand: str
    tijdlijn_start: float = 0.0
    bron_start: float = 0.0
    duur: float = 0.0
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 2.0
    soort: str = "muziek"  # muziek | sfx | voice


@dataclass
class Grade:
    """Kleurbewerking. Bewust klein gehouden - de AI kiest, niet de gebruiker."""

    contrast: float = 1.0
    verzadiging: float = 1.0
    helderheid: float = 0.0
    warmte: float = 0.0  # -1 koel .. +1 warm


@dataclass
class Look:
    """Welke van de 24 looks (§4.3) eroverheen gaat, en hoe sterk."""

    id: str = "geen"
    sterkte: float = 1.0


@dataclass
class Afwerking:
    """Afwerking uit §4.3. Alles 0..1; 0 betekent uit."""

    korrel: float = 0.0
    halation: float = 0.0
    gloed: float = 0.0
    vignet: float = 0.0
    lichtlek: float = 0.0
    breedbeeld: float = 0.0
    filmtrilling: float = 0.0
    kleurrand: float = 0.0


def _keur_kader(b: VideoBlok) -> None:
    """Een kaderpunt ligt binnen het beeld, en keyframes staan op volgorde."""
    k = b.kader
    if not k:
        return
    if not isinstance(k, dict):
        raise EDLFout(f"Blok {b.id}: kader moet een object zijn, niet {type(k).__name__}.")
    onbekend = set(k) - {"x", "y", "punten"}
    if onbekend:
        raise EDLFout(f"Blok {b.id}: kader heeft onbekende velden {sorted(onbekend)}.")

    punten = k.get("punten")
    if punten is not None:
        if "x" in k or "y" in k:
            raise EDLFout(
                f"Blok {b.id}: kader heeft zowel een vast punt als keyframes. "
                "Kies er één, anders is niet te zeggen welke de renderer volgt."
            )
        if not punten:
            raise EDLFout(f"Blok {b.id}: kader heeft een lege lijst keyframes.")
        vorige = -1.0
        for p in punten:
            t = float(p.get("t", 0.0))
            if not 0.0 <= t <= 1.0:
                raise EDLFout(f"Blok {b.id}: kaderpunt t={t} valt buiten 0..1.")
            if t <= vorige:
                raise EDLFout(f"Blok {b.id}: kaderpunten staan niet op volgorde.")
            vorige = t
            _keur_kaderpunt(b, p)
        return
    _keur_kaderpunt(b, k)


def _keur_kaderpunt(b: VideoBlok, p: dict) -> None:
    for as_ in ("x", "y"):
        if as_ not in p:
            continue
        w = float(p[as_])
        if not 0.0 <= w <= 1.0:
            raise EDLFout(f"Blok {b.id}: kader {as_}={w} valt buiten 0..1.")


def _keur_verloop(b: VideoBlok) -> None:
    """Een speed-ramp moet oplopen in tijd en nergens stilstaan of achteruit."""
    vorige = -1.0
    for punt in b.snelheid_verloop:
        t, snelheid = float(punt["t"]), float(punt["snelheid"])
        if not 0.0 <= t <= 1.0:
            raise EDLFout(f"Blok {b.id}: snelheidspunt t={t} valt buiten 0..1.")
        if t <= vorige:
            raise EDLFout(f"Blok {b.id}: snelheidspunten staan niet op volgorde.")
        if snelheid <= 0:
            raise EDLFout(f"Blok {b.id}: snelheid {snelheid} in het verloop.")
        vorige = t


@dataclass
class EDL:
    project: str
    stijl: str = "actie"
    merk: str = "prive"
    versie: int = SCHEMA_VERSIE
    canvas: Canvas = field(default_factory=Canvas)
    grade: Grade = field(default_factory=Grade)
    look: Look = field(default_factory=Look)
    afwerking: Afwerking = field(default_factory=Afwerking)
    # Eén seed voor alle ruis (korrel, filmtrilling, lichtlek). Preview en
    # export rekenen dezelfde ruis uit (frame-index, seed) - nooit random.
    effectseed: int = 0
    # Waarmee deze montage bedacht is: {"stijl", "vorm", "duur"}. Hieraan ziet
    # `montage.regie_nodig()` of er sinds de laatste regie een bewuste keuze in
    # Stijl veranderd is. Zonder dit zou elke render opnieuw regisseren en elke
    # handmatige wijziging uit stap 4 weggooien.
    brief: dict = field(default_factory=dict)
    video: list[VideoBlok] = field(default_factory=list)
    overlay: list[OverlayBlok] = field(default_factory=list)
    audio: list[AudioSpoor] = field(default_factory=list)
    notities: str = ""

    @property
    def duur(self) -> float:
        eindes = [b.tijdlijn_eind for b in self.video]
        return round(max(eindes), 3) if eindes else 0.0

    # -- opslaan en laden ---------------------------------------------------

    def naar_dict(self) -> dict:
        return {
            "versie": self.versie,
            "project": self.project,
            "stijl": self.stijl,
            "merk": self.merk,
            "canvas": asdict(self.canvas),
            "grade": asdict(self.grade),
            "look": asdict(self.look),
            "afwerking": asdict(self.afwerking),
            "effectseed": self.effectseed,
            "brief": self.brief,
            "duur": self.duur,
            "video": [asdict(b) for b in self.video],
            "overlay": [asdict(b) for b in self.overlay],
            "audio": [asdict(a) for a in self.audio],
            "notities": self.notities,
        }

    def schrijf(self, pad: Path) -> Path:
        """Sla op zonder het oude bestand te kunnen verliezen.

        Regel 3 zegt dat dit bestand de enige waarheid is. Een gewone
        `write_text` kapt het bestand eerst af; gaat de stroom er dan uit, dan
        is de montage weg. Daarom: eerst naast het bestand schrijven, dan in
        één keer op zijn plek zetten (`replace` is atomair op Mac en Windows).
        De vorige versie blijft als `<naam>.vorige.json` staan, zodat een
        verkeerde wijziging ook terug te draaien is.
        """
        self.valideer()
        pad.parent.mkdir(parents=True, exist_ok=True)
        deel = pad.with_name(pad.name + ".deel")
        deel.write_text(
            json.dumps(self.naar_dict(), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        if pad.exists():
            # Kopiëren, niet verplaatsen: anders is er een moment waarop
            # `edl.json` even niet bestaat.
            shutil.copy2(pad, pad.with_name(f"{pad.stem}.vorige{pad.suffix}"))
        deel.replace(pad)
        return pad

    @classmethod
    def lees(cls, pad: Path) -> EDL:
        d = json.loads(pad.read_text(encoding="utf-8"))
        return cls.van_dict(d)

    @classmethod
    def van_dict(cls, d: dict) -> EDL:
        if d.get("versie", 1) > SCHEMA_VERSIE:
            raise EDLFout(
                f"EDL-versie {d['versie']} is nieuwer dan deze engine ({SCHEMA_VERSIE}) aankan."
            )
        edl = cls(
            project=d["project"],
            stijl=d.get("stijl", "actie"),
            merk=d.get("merk", "prive"),
            canvas=Canvas(**d.get("canvas", {})),
            grade=Grade(**d.get("grade", {})),
            look=Look(**d.get("look", {})),
            afwerking=Afwerking(**d.get("afwerking", {})),
            effectseed=int(d.get("effectseed", 0)),
            brief=dict(d.get("brief") or {}),
            notities=d.get("notities", ""),
        )
        for b in d.get("video", []):
            over = b.pop("overgang_in", None) or {}
            edl.video.append(VideoBlok(**b, overgang_in=Overgang(**over)))
        for o in d.get("overlay", []):
            edl.overlay.append(OverlayBlok(**o))
        for a in d.get("audio", []):
            edl.audio.append(AudioSpoor(**a))
        return edl

    # -- bewerken -----------------------------------------------------------

    def op_framerooster(self) -> None:
        """Zet alle tijden op hele frames en sluit de blokken naadloos aaneen.

        Dit is niet cosmetisch. Een shot van 1,95 s is bij 30 fps 58,5 frames;
        ffmpeg maakt daar 58 of 59 van en die afrondingsfout stapelt op. Na een
        stuk of vijf shots loopt de montage uit de pas met de EDL en blijft het
        laatste frame van het vorige shot een frame hangen - zichtbaar als een
        flits bij elke overgang.

        Een frame is bij 30 fps 33 ms, en de beat-uitlijning was toch al niet
        preciezer dan een frame. We verliezen dus niets.
        """
        fps = self.canvas.fps
        if not self.video or fps <= 0:
            return
        self.video.sort(key=lambda b: b.tijdlijn_start)

        # Snijpunten op hele frames, daarna duur = verschil tussen twee punten.
        punten = [round(b.tijdlijn_start * fps) for b in self.video]
        einde = round((self.video[-1].tijdlijn_start + self.video[-1].duur) * fps)

        # Zorg dat elk punt minstens een frame na het vorige ligt.
        for i in range(1, len(punten)):
            punten[i] = max(punten[i], punten[i - 1] + 1)
        einde = max(einde, punten[-1] + 1)

        for i, b in enumerate(self.video):
            volgend = punten[i + 1] if i + 1 < len(punten) else einde
            b.tijdlijn_start = round(punten[i] / fps, 6)
            b.frames = volgend - punten[i]
            b.duur = round(b.frames / fps, 6)

    def sorteer(self) -> None:
        """Zet blokken op volgorde. Raakt de tijden niet aan.

        Let op: gebruik dit, niet `pak_aan`, als de tijdlijn op de muziek is
        uitgelijnd. Aaneenschuiven verschuift elke snede en dan is beat-sync
        weg - dat kostte hier een render om te ontdekken.
        """
        self.video.sort(key=lambda b: b.tijdlijn_start)
        self.overlay.sort(key=lambda o: o.tijdlijn_start)

    def pak_aan(self) -> None:
        """Sluit gaten in de tijdlijn. Alleen na het verwijderen van een blok,
        en alleen als de montage niet op muziek is uitgelijnd."""
        self.sorteer()
        t = 0.0
        for b in self.video:
            b.tijdlijn_start = round(t, 3)
            t += b.duur

    def valideer(self) -> None:
        if not self.video:
            raise EDLFout("EDL heeft geen videoblokken.")

        ids = [b.id for b in self.video]
        if len(ids) != len(set(ids)):
            raise EDLFout("Dubbele blok-id's in het videospoor.")

        vorige_eind = -1e-6
        for b in sorted(self.video, key=lambda x: x.tijdlijn_start):
            if b.duur <= 0:
                raise EDLFout(f"Blok {b.id} heeft duur {b.duur}.")
            if b.bron_start < 0:
                raise EDLFout(f"Blok {b.id} heeft negatieve bron_start.")
            if b.snelheid <= 0:
                raise EDLFout(f"Blok {b.id} heeft snelheid {b.snelheid}.")
            if b.tijdlijn_start < vorige_eind - 1e-3:
                raise EDLFout(
                    f"Blok {b.id} begint op {b.tijdlijn_start}s maar het vorige "
                    f"blok loopt tot {vorige_eind}s. Videoblokken mogen niet overlappen."
                )
            if b.vulmodus not in ("vul", "pas", "wazig"):
                raise EDLFout(f"Blok {b.id} heeft onbekende vulmodus '{b.vulmodus}'.")
            if b.overgang_in.soort not in OVERGANGEN:
                raise EDLFout(
                    f"Blok {b.id} heeft onbekende overgang '{b.overgang_in.soort}'."
                )
            _keur_verloop(b)
            _keur_kader(b)
            vorige_eind = b.tijdlijn_eind

        for o in self.overlay:
            if o.duur <= 0:
                raise EDLFout(f"Overlay {o.id} heeft duur {o.duur}.")

    def samenvatting(self) -> str:
        regels = [
            f"EDL  {self.project}  ·  stijl {self.stijl}  ·  merk {self.merk}",
            f"{self.canvas.breedte}x{self.canvas.hoogte}@{self.canvas.fps}  ·  "
            f"{len(self.video)} blokken  ·  {self.duur:.1f}s",
        ]
        if self.audio:
            a = self.audio[0]
            regels.append(f"muziek: {a.bestand} vanaf {a.bron_start:.1f}s")
        regels.append("")
        regels.append(f"{'#':>3} {'tijd':>7} {'duur':>6} {'clip':5} {'bron':>7}  reden")
        for i, b in enumerate(self.video, 1):
            slot = "*" if b.vast else " "
            regels.append(
                f"{i:>3}{slot}{b.tijdlijn_start:>7.1f}{b.duur:>6.1f} {b.clip:5}"
                f"{b.bron_start:>7.1f}  {b.reden}"
            )
        if self.overlay:
            regels.append("")
            regels.append("overlays:")
            for o in self.overlay:
                tekst = o.inhoud.get("tekst", "")
                regels.append(
                    f"  {o.tijdlijn_start:>6.1f}s +{o.duur:.1f}s  {o.soort:11} {tekst}"
                )
        return "\n".join(regels)
