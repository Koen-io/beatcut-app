"""Fase 7 - zelf-evaluatie.

Kijkt de gerenderde video na *voordat* een mens hem ziet, en meet daarbij
precies die dingen die je met het blote oog pas na drie keer terugkijken
opmerkt: een frame drift, een shot dat stiekem stilstaat, een snede die
naast de tel valt, een titel die net buiten de veilige marge steekt.

Dezelfde regel als bij `analyze/`: **alles wat een computer kan meten, meet
de computer.** Er komt hier geen model aan te pas. Elke bevinding heeft een
getal en een drempel, en beide staan in het rapport - zodat je kunt zien
waarom iets is aangemerkt en niet hoeft te raden.

Uitvoer: een leesbaar rapport op de terminal en `review.json` in de
projectmap. De exitcode is 1 zodra er een `fout` tussen zit, zodat dit in
een script of een latere automatische herrender-lus te gebruiken is.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import media, paths
from .edl import EDL

# --------------------------------------------------------------------------
# Drempels. Bewust hier bij elkaar, net als analyze/kalibratie.py: een
# drempel die je niet kunt vinden, kun je ook niet bijstellen.
# --------------------------------------------------------------------------

# Beat-uitlijning. Een frame is bij 30 fps 33 ms; preciezer dan een frame kan
# een snede niet liggen, dus daar leggen we de grens ook.
BEAT_GOED_MS = 40.0
BEAT_SLECHT_MS = 90.0

# Bevroren beeld. -40 dB is op eigen materiaal geijkt: daaronder vindt hij de
# bedoelde freeze frames en verder niets, daarboven (-30 dB) gaat hij elk
# rustig landschapsshot aanwijzen.
FREEZE_DREMPEL_DB = -40
FREEZE_MIN_DUUR = 0.4
# Waar we pas iets van zeggen. Korter dan een seconde stilstand valt in een
# montage niemand op; daar een waarschuwing van maken maakt het rapport
# ruis, en een rapport vol ruis leest niemand meer.
FREEZE_MELD_VANAF = 1.0

# Zwart beeld. Alleen buiten de bedoelde dips en buiten de eerste/laatste
# halve seconde is dat een probleem.
ZWART_MIN_DUUR = 0.08
ZWART_PIXELDREMPEL = 0.08

# Scherpte per shot, op de schaal van analyze/kalibratie.py (0..1).
SCHERPTE_ONDERGRENS = 0.25

# Luidheid: dezelfde norm als de renderer aanhoudt, uit media.py. Zou de
# review een eigen doel hanteren, dan kan een render die precies goed is toch
# worden afgekeurd.
LUIDHEID_DOEL = media.LUFS_DOEL
LUIDHEID_MARGE = 1.5
TRUE_PEAK_MAX = media.TRUE_PEAK_DOEL

# Herhaling: dezelfde bronclip binnen dit aantal shots terug is opvallend.
HERHALING_VENSTER = 4


# Elke bevinding heeft twee formuleringen. De lange staat in `boodschap`, met
# getallen en drempels erbij - die is voor de terminal en voor het uitzoeken
# waar iets misging. De korte hangt aan de code en is wat de wizard laat zien:
# geen seconden, geen dB, alleen wat je eraan hebt.
# Let op: dit zijn de teksten voor als er iets *aan de hand* is. Een bevinding
# met ernst "ok" krijgt zijn eigen boodschap; die wordt in de wizard toch niet
# getoond. Eén tekst voor beide zou "geen enkele opname komt te snel terug"
# als waarschuwing opleveren, en dat leest als onzin.
KORT = {
    "frames": "De video is niet precies zo lang geworden als bedoeld.",
    "canvas": "Het beeldformaat wijkt af van wat je gekozen hebt.",
    "zwart": "Er zit een stukje zwart beeld in waar dat niet hoort.",
    "freeze_mist": "Een bevroren beeld is niet in de video terechtgekomen.",
    "stilstand": "Een shot staat een tijdje helemaal stil.",
    "luidheid": "Het geluid staat harder of zachter dan platforms verwachten.",
    "klipping": "Het geluid staat te hard en vervormt.",
    "stilte": "Er komt geen geluid uit de video.",
    "geluid": "De video heeft geen geluidsspoor.",
    "beat": "Een paar snedes vallen net naast de muziek.",
    "scherpte": "Een paar shots zijn wat onscherp.",
    "herhaling": "Dezelfde opname komt kort na elkaar terug. Met meer verschillende beelden wordt het gevarieerder.",
    "overlay_ontbreekt": "Een titel is niet in de video terechtgekomen.",
    "overlay_leeg": "Een titel is leeg gebleven.",
}


@dataclass
class Bevinding:
    ernst: str  # fout | let op | ok
    code: str
    boodschap: str
    details: dict = field(default_factory=dict)

    @property
    def kort(self) -> str:
        """Dezelfde bevinding zonder cijfers, voor wie geen editor is."""
        return KORT.get(self.code, self.boodschap)


@dataclass
class Rapport:
    project: str
    bestand: str
    bevindingen: list[Bevinding] = field(default_factory=list)

    def voeg_toe(self, ernst: str, code: str, boodschap: str, **details) -> None:
        self.bevindingen.append(Bevinding(ernst, code, boodschap, details))

    @property
    def fouten(self) -> list[Bevinding]:
        return [b for b in self.bevindingen if b.ernst == "fout"]

    @property
    def waarschuwingen(self) -> list[Bevinding]:
        return [b for b in self.bevindingen if b.ernst == "let op"]

    @property
    def geslaagd(self) -> bool:
        return not self.fouten

    def naar_dict(self) -> dict:
        return {
            "project": self.project,
            "bestand": self.bestand,
            "geslaagd": self.geslaagd,
            "fouten": len(self.fouten),
            "waarschuwingen": len(self.waarschuwingen),
            "bevindingen": [{**asdict(b), "kort": b.kort} for b in self.bevindingen],
        }

    def tekst(self) -> str:
        merk = {"fout": "FOUT  ", "let op": "let op", "ok": "  ok  "}
        regels = [f"Review  {self.project}  ·  {Path(self.bestand).name}", ""]
        for b in self.bevindingen:
            regels.append(f"  {merk.get(b.ernst, '      ')}  {b.boodschap}")
        regels.append("")
        if self.fouten:
            regels.append(
                f"{len(self.fouten)} fout(en), {len(self.waarschuwingen)} waarschuwing(en)."
            )
        elif self.waarschuwingen:
            regels.append(
                f"Geen fouten, {len(self.waarschuwingen)} waarschuwing(en) om naar te kijken."
            )
        else:
            regels.append("Alles in orde.")
        return "\n".join(regels)


# --------------------------------------------------------------------------
# Meetgereedschap - dunne laag rond ffmpeg, net als media.py
# --------------------------------------------------------------------------


def _ffmpeg_meting(bestand: Path, args: list[str], *, timeout: int = 1800) -> str:
    """Draai een filter met `-f null` en geef stdout+stderr terug.

    De meetfilters van ffmpeg (blackdetect, freezedetect, ebur128, cropdetect)
    schrijven hun uitkomst naar het log, niet naar een bestand. Vandaar dat we
    beide stromen samenvoegen en er daarna doorheen lezen.
    """
    r = subprocess.run(
        [str(paths.ffmpeg()), "-hide_banner", "-v", "info", "-i", str(bestand),
         *args, "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (r.stdout or "") + "\n" + (r.stderr or "")


def _frames(bestand: Path) -> int:
    r = subprocess.run(
        [str(paths.ffprobe()), "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", str(bestand)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    cijfers = re.findall(r"\d+", r.stdout or "")
    return int(cijfers[0]) if cijfers else 0


def _zwarte_stukken(bestand: Path) -> list[tuple[float, float]]:
    uit = _ffmpeg_meting(
        bestand,
        ["-vf", f"blackdetect=d={ZWART_MIN_DUUR}:pix_th={ZWART_PIXELDREMPEL}"],
    )
    stukken = []
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", uit):
        stukken.append((float(m.group(1)), float(m.group(2))))
    return stukken


def _bevroren_stukken(bestand: Path) -> list[tuple[float, float]]:
    uit = _ffmpeg_meting(
        bestand,
        ["-vf",
         f"freezedetect=n={FREEZE_DREMPEL_DB}dB:d={FREEZE_MIN_DUUR},"
         "metadata=mode=print:file=-"],
    )
    stukken: list[tuple[float, float]] = []
    start: float | None = None
    for regel in uit.splitlines():
        m = re.search(r"freeze_start=([\d.]+)", regel)
        if m:
            start = float(m.group(1))
            continue
        m = re.search(r"freeze_duration=([\d.]+)", regel)
        if m and start is not None:
            stukken.append((start, start + float(m.group(1))))
            start = None
    return _samenvoegen(stukken)


def _samenvoegen(stukken: list[tuple[float, float]], gat: float = 0.2) -> list[tuple[float, float]]:
    """Plak stukken aan elkaar die praktisch tegen elkaar aan liggen.

    freezedetect knipt een lang stilstaand shot op in stukjes van een halve
    seconde. Vijf regels over hetzelfde shot lezen als vijf problemen, en dat
    is er een.
    """
    if not stukken:
        return []
    uit = [list(stukken[0])]
    for a, b in stukken[1:]:
        if a <= uit[-1][1] + gat:
            uit[-1][1] = max(uit[-1][1], b)
        else:
            uit.append([a, b])
    return [(a, b) for a, b in uit]


def _luidheid(bestand: Path) -> dict[str, float] | None:
    """Integrated loudness en true peak volgens EBU R128.

    Let op: hier geen `-map` bij. Een expliciete map pakt de ruwe invoerstroom
    en zet de filterketen buitenspel; ebur128 meet dan niets en meldt keurig
    -70 LUFS alsof het spoor stil is.
    """
    uit = _ffmpeg_meting(bestand, ["-af", "ebur128=peak=true"])

    def laatste(patroon: str) -> float | None:
        # ebur128 dreunt tijdens het meten elke seconde een tussenstand op met
        # dezelfde velden. Alleen de laatste regel is de eindstand; de eerste
        # is per definitie -70 LUFS, want daar is nog niets gemeten.
        treffers = re.findall(patroon, uit)
        return float(treffers[-1]) if treffers else None

    i = laatste(r"I:\s*(-?[\d.]+)\s*LUFS")
    if i is None:
        return None
    return {
        "lufs": i,
        "lra": laatste(r"LRA:\s*(-?[\d.]+)\s*LU") or 0.0,
        "true_peak": laatste(r"Peak:\s*(-?[\d.]+)\s*dBFS") or 0.0,
    }


def _alfa_zichtbaar(mov: Path) -> tuple[int, int]:
    """Hoeveel frames van deze overlay hebben zichtbare beeldinhoud?

    Teruggave: (frames met inhoud, frames totaal).

    Dit is de controle die ertoe doet. Een overlay die leeg of te kort uit de
    renderer komt is drie keer eerder in dit project voorgekomen - een
    `data-duration` die een script te laat zette, clips die met JavaScript
    waren aangemaakt, een wortelelement dat zelf `class="clip"` droeg. In alle
    drie de gevallen kwam er een bestand uit dat er prima uitzag en nergens
    beeld in had.

    Waarom hier géén marge-controle meer staat: die keek naar het omhullende
    kader van het alfakanaal, en daar zit de slagschaduw van de titelkaart in.
    Gemeten op een titel die keurig binnen de marges stond: het kader liep tot
    de onderrand van het beeld, ook bij een drempel van 250 van de 255. Kaart
    en schaduw zijn in het alfakanaal niet uit elkaar te houden, en een
    waarschuwing die bij elke correcte titel afgaat is erger dan geen
    waarschuwing.
    """
    uit = _ffmpeg_meting(mov, ["-vf", "alphaextract,bbox=min_val=96"], timeout=900)
    kaders = [
        tuple(int(v) for v in m)
        for m in re.findall(r"x1:(-?\d+) x2:(-?\d+) y1:(-?\d+) y2:(-?\d+)", uit)
    ]
    gevuld = sum(1 for k in kaders if k[1] >= k[0] and k[3] >= k[2])
    return gevuld, len(kaders)


def _alfa_kader(mov: Path) -> tuple[int, int, int, int] | None:
    """Het kleinste rechthoekje waar alle zichtbare pixels van een overlay in passen.

    `alphaextract` maakt van het alfakanaal een grijsbeeld, `bbox` geeft daar
    per frame de omhullende rechthoek van. Zo weten we waar de titel echt
    staat, zonder aannames over het sjabloon.

    `cropdetect` leek hier logischer maar is het niet: die werkt met een
    zwartdrempel op 0..255 en gaf op deze bestanden of het hele beeld of
    helemaal niets terug. `bbox` heeft een expliciete `min_val` en is dus
    voorspelbaar.

    **Niet de vereniging over alle frames.** Een titel schuift of vervaagt in
    beeld; de vereniging pakt dan ook de startpositie mee, en die ligt vaak
    net buiten het kader. Gemeten op de titelkaart: vereniging y 703-1079
    (tot de onderrand), terwijl de titel eenmaal op zijn plek netjes binnen de
    marge staat. Daarom het middelste frame - daar staat de animatie stil.

    Teruggave: (x1, y1, x2, y2) van het middelste zichtbare frame.
    """
    uit = _ffmpeg_meting(mov, ["-vf", "alphaextract,bbox=min_val=96"], timeout=900)
    kaders = [
        tuple(int(v) for v in m)
        for m in re.findall(r"x1:(-?\d+) x2:(-?\d+) y1:(-?\d+) y2:(-?\d+)", uit)
    ]
    # Frames zonder zichtbare pixels leveren een omgekeerde rechthoek op.
    kaders = [k for k in kaders if k[1] >= k[0] and k[3] >= k[2]]
    if not kaders:
        return None
    x1, x2, y1, y2 = kaders[len(kaders) // 2]
    return x1, y1, x2, y2


# --------------------------------------------------------------------------
# De controles
# --------------------------------------------------------------------------


def _overlappen(a: tuple[float, float], b: tuple[float, float], marge: float = 0.2) -> bool:
    return a[0] < b[1] + marge and b[0] < a[1] + marge


def _controleer_frames(rap: Rapport, bestand: Path, edl: EDL) -> None:
    verwacht = sum(
        max(1, b.frames or round(b.duur * edl.canvas.fps)) for b in edl.video
    )
    gemeten = _frames(bestand)
    verschil = gemeten - verwacht
    if verschil == 0:
        rap.voeg_toe(
            "ok", "frames",
            f"Framevast: {gemeten} frames, precies wat de EDL voorschrijft.",
            verwacht=verwacht, gemeten=gemeten,
        )
    else:
        rap.voeg_toe(
            "fout", "frames",
            f"Frameaantal wijkt af: {gemeten} in de render, {verwacht} in de EDL "
            f"({verschil:+d}). Er is een blok dat niet oplevert wat het belooft.",
            verwacht=verwacht, gemeten=gemeten, verschil=verschil,
        )


def _controleer_beeldformaat(rap: Rapport, bestand: Path, edl: EDL) -> None:
    info = media.probe(bestand)
    goed = info.breedte == edl.canvas.breedte and info.hoogte == edl.canvas.hoogte
    ernst = "ok" if goed else "fout"
    rap.voeg_toe(
        ernst, "canvas",
        f"Beeldformaat {info.breedte}x{info.hoogte}"
        + ("" if goed else f", maar de EDL vraagt {edl.canvas.breedte}x{edl.canvas.hoogte}."),
        gemeten=[info.breedte, info.hoogte],
        verwacht=[edl.canvas.breedte, edl.canvas.hoogte],
    )


def _controleer_zwart(rap: Rapport, bestand: Path, edl: EDL) -> None:
    stukken = _zwarte_stukken(bestand)
    duur = edl.duur

    # Bedoeld zwart: een dip naar zwart, en de eerste en laatste halve seconde
    # (daar zit vaak een fade in of uit).
    bedoeld = [(0.0, 0.6), (max(0.0, duur - 0.6), duur + 1.0)]
    for b in edl.video:
        if b.overgang_in.soort == "dip_zwart":
            bedoeld.append((b.tijdlijn_start, b.tijdlijn_start + b.overgang_in.duur + 0.2))

    onverwacht = [s for s in stukken if not any(_overlappen(s, v) for v in bedoeld)]
    if not onverwacht:
        rap.voeg_toe(
            "ok", "zwart",
            f"Geen onbedoeld zwart beeld ({len(stukken)} gevonden, allemaal verklaard).",
            gevonden=len(stukken),
        )
        return
    plek = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in onverwacht[:5])
    rap.voeg_toe(
        "fout", "zwart",
        f"{len(onverwacht)} stuk(ken) zwart beeld waar geen dip staat: {plek}.",
        stukken=onverwacht,
    )


def _controleer_bevroren(rap: Rapport, bestand: Path, edl: EDL) -> None:
    stukken = _bevroren_stukken(bestand)
    fps = edl.canvas.fps

    bedoeld = []
    for b in edl.video:
        if b.bevriezen > 0:
            frames = max(1, b.frames or round(b.duur * fps))
            stil = min(frames - 1, max(1, round(b.bevriezen * fps)))
            begin = b.tijdlijn_start + (frames - stil) / fps
            bedoeld.append((begin, begin + stil / fps))

    gevonden_bedoeld = [s for s in stukken if any(_overlappen(s, v) for v in bedoeld)]
    onverwacht = [s for s in stukken if not any(_overlappen(s, v) for v in bedoeld)]

    if bedoeld and len(gevonden_bedoeld) < len(bedoeld):
        rap.voeg_toe(
            "fout", "freeze_mist",
            f"{len(bedoeld)} freeze frame(s) in de EDL, maar er zijn er "
            f"{len(gevonden_bedoeld)} terug te vinden in het beeld.",
            bedoeld=bedoeld, gevonden=gevonden_bedoeld,
        )
    elif bedoeld:
        rap.voeg_toe(
            "ok", "freeze",
            f"{len(bedoeld)} freeze frame(s) staan waar ze horen.",
            bedoeld=bedoeld,
        )

    onverwacht = [s for s in onverwacht if s[1] - s[0] >= FREEZE_MELD_VANAF]
    if onverwacht:
        plek = ", ".join(f"{a:.1f}s ({b - a:.1f}s)" for a, b in onverwacht[:5])
        rap.voeg_toe(
            "let op", "stilstand",
            f"{len(onverwacht)} stuk(ken) beeld staan stil zonder dat dat gevraagd is: "
            f"{plek}. Meestal is dat een statisch shot - Ken Burns lost het op.",
            stukken=onverwacht,
        )


def _controleer_beat(rap: Rapport, edl: EDL, analyse: dict | None) -> None:
    beats = ((analyse or {}).get("muziek") or {}).get("beats") or []
    if not beats or not edl.audio:
        rap.voeg_toe(
            "ok", "beat", "Geen muziek of geen beat-raster - beat-controle overgeslagen."
        )
        return

    verschuiving = edl.audio[0].bron_start
    afwijkingen = []
    for b in edl.video[1:]:  # het eerste blok begint op 0; dat is geen snede
        t = b.tijdlijn_start + verschuiving
        dichtst = min(beats, key=lambda x: abs(x - t))
        afwijkingen.append(abs(dichtst - t) * 1000.0)

    if not afwijkingen:
        return
    gem = sum(afwijkingen) / len(afwijkingen)
    ergste = max(afwijkingen)
    slecht = [a for a in afwijkingen if a > BEAT_SLECHT_MS]

    if not slecht and gem <= BEAT_GOED_MS:
        rap.voeg_toe(
            "ok", "beat",
            f"Snedes liggen op de tel: gemiddeld {gem:.0f} ms ernaast, "
            f"slechtste {ergste:.0f} ms ({ergste / 1000 * edl.canvas.fps:.1f} frame).",
            gemiddeld_ms=round(gem, 1), ergste_ms=round(ergste, 1),
        )
    else:
        rap.voeg_toe(
            "let op", "beat",
            f"{len(slecht)} van {len(afwijkingen)} snedes vallen meer dan "
            f"{BEAT_SLECHT_MS:.0f} ms naast de tel (gemiddeld {gem:.0f} ms, "
            f"slechtste {ergste:.0f} ms).",
            gemiddeld_ms=round(gem, 1), ergste_ms=round(ergste, 1), slecht=len(slecht),
        )


def _shots_van(analyse: dict, clip_id: str) -> list[dict]:
    for c in analyse.get("clips", []):
        if c.get("id") == clip_id:
            return c.get("shots", []) or []
    return []


def _controleer_scherpte(rap: Rapport, edl: EDL, analyse: dict | None) -> None:
    if not analyse:
        return
    zwak = []
    for b in edl.video:
        shots = _shots_van(analyse, b.clip)
        raak = [
            s for s in shots
            if s["eind"] > b.bron_start and s["start"] < b.bron_start + b.duur * b.snelheid
        ]
        if not raak:
            continue
        # De beste van de overlappende shots telt: een blok dat net over een
        # shotgrens heen valt hoeft niet afgerekend te worden op de slechtste.
        score = max(s.get("scherpte", 0.0) for s in raak)
        if score < SCHERPTE_ONDERGRENS:
            zwak.append((b.id, b.clip, round(score, 3)))

    if not zwak:
        rap.voeg_toe(
            "ok", "scherpte",
            f"Alle {len(edl.video)} shots halen de scherptedrempel "
            f"({SCHERPTE_ONDERGRENS:.2f}).",
        )
    else:
        lijst = ", ".join(f"{i} ({c}, {s:.2f})" for i, c, s in zwak[:5])
        rap.voeg_toe(
            "let op", "scherpte",
            f"{len(zwak)} shot(s) onder de scherptedrempel: {lijst}.",
            shots=zwak,
        )


def _controleer_herhaling(rap: Rapport, edl: EDL) -> None:
    botsingen = []
    for i, b in enumerate(edl.video):
        for j in range(max(0, i - HERHALING_VENSTER), i):
            if edl.video[j].clip == b.clip:
                botsingen.append((edl.video[j].id, b.id, b.clip))
                break
    if not botsingen:
        rap.voeg_toe(
            "ok", "herhaling",
            f"Geen bronclip komt binnen {HERHALING_VENSTER} shots terug.",
        )
    else:
        lijst = ", ".join(f"{a}+{b} ({c})" for a, b, c in botsingen[:5])
        rap.voeg_toe(
            "let op", "herhaling",
            f"{len(botsingen)} keer komt dezelfde bronclip binnen "
            f"{HERHALING_VENSTER} shots terug: {lijst}.",
            botsingen=botsingen,
        )


def _controleer_luidheid(rap: Rapport, bestand: Path) -> None:
    info = media.probe(bestand)
    if not info.heeft_audio:
        rap.voeg_toe("fout", "geluid", "De render heeft geen geluidsspoor.")
        return

    meting = _luidheid(bestand)
    if not meting:
        rap.voeg_toe("let op", "luidheid", "Luidheid kon niet gemeten worden.")
        return

    lufs, piek = meting["lufs"], meting["true_peak"]
    if lufs <= -60.0:
        rap.voeg_toe(
            "fout", "stilte",
            f"Het geluidsspoor is praktisch stil ({lufs:.1f} LUFS).",
            **meting,
        )
        return
    afwijking = lufs - LUIDHEID_DOEL

    if abs(afwijking) <= LUIDHEID_MARGE:
        rap.voeg_toe(
            "ok", "luidheid",
            f"Luidheid {lufs:.1f} LUFS (doel {LUIDHEID_DOEL:.0f}), "
            f"true peak {piek:.1f} dBTP.",
            **meting,
        )
    else:
        richting = "te luid" if afwijking > 0 else "te zacht"
        rap.voeg_toe(
            "let op", "luidheid",
            f"Luidheid {lufs:.1f} LUFS is {abs(afwijking):.1f} dB {richting} "
            f"(doel {LUIDHEID_DOEL:.0f} LUFS). Platforms regelen dat terug.",
            **meting,
        )

    if piek > TRUE_PEAK_MAX:
        rap.voeg_toe(
            "fout", "klipping",
            f"True peak {piek:.1f} dBTP ligt boven {TRUE_PEAK_MAX:.0f} dBTP. "
            f"Dat klipt hoorbaar zodra een platform hercodeert.",
            true_peak=piek,
        )


def _controleer_overlays(rap: Rapport, edl: EDL, pdir: Path) -> None:
    map_ = pdir / "composities"
    if not edl.overlay or not map_.exists():
        return

    leeg: list[str] = []
    ontbreekt: list[str] = []
    gemeten = 0

    for o in edl.overlay:
        mov = map_ / f"{o.id}.mov"
        if not mov.exists():
            ontbreekt.append(o.id)
            continue
        gevuld, totaal = _alfa_zichtbaar(mov)
        gemeten += 1
        # Een overlay die in minder dan een tiende van zijn frames iets laat
        # zien, is in de praktijk leeg: dat is precies hoe een mislukte
        # compositie eruitziet.
        if totaal == 0 or gevuld < max(1, totaal // 10):
            leeg.append(o.id)

    if ontbreekt:
        rap.voeg_toe(
            "fout", "overlay_ontbreekt",
            f"{len(ontbreekt)} titel(s) zijn niet gerenderd: {', '.join(ontbreekt)}.",
            overlays=ontbreekt,
        )
    if leeg:
        rap.voeg_toe(
            "fout", "overlay_leeg",
            f"{len(leeg)} titel(s) leveren een leeg beeld op: {', '.join(leeg)}. "
            f"Meestal een compositie die de renderer niet kon lezen.",
            overlays=leeg,
        )
    if gemeten and not leeg and not ontbreekt:
        rap.voeg_toe(
            "ok", "overlay",
            f"Alle {gemeten} titel(s) zijn zichtbaar in beeld.",
            gemeten=gemeten,
        )


# --------------------------------------------------------------------------
# Ingang
# --------------------------------------------------------------------------


def review(project: str, *, bestand: Path | None = None, log=print) -> Rapport:
    """Kijk de laatste render na en schrijf `review.json`."""
    pdir = paths.project_dir(project)
    edl = EDL.lees(pdir / "edl.json")

    if bestand is None:
        kandidaten = sorted(
            (pdir / "renders").glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        kandidaten = [p for p in kandidaten if "snel" not in p.stem]
        if not kandidaten:
            raise media.MediaFout(
                f"Geen render gevonden in {pdir / 'renders'}. Draai eerst: cve render {project}"
            )
        bestand = kandidaten[0]

    analyse_pad = pdir / "analysis.json"
    analyse = (
        json.loads(analyse_pad.read_text(encoding="utf-8"))
        if analyse_pad.exists()
        else None
    )

    rap = Rapport(project=project, bestand=str(bestand))
    log(f"Review {bestand.name} ...")

    # Volgorde met opzet: eerst wat de montage kapot maakt, dan wat hem
    # minder mooi maakt.
    _controleer_frames(rap, bestand, edl)
    _controleer_beeldformaat(rap, bestand, edl)
    _controleer_zwart(rap, bestand, edl)
    _controleer_bevroren(rap, bestand, edl)
    _controleer_luidheid(rap, bestand)
    _controleer_beat(rap, edl, analyse)
    _controleer_scherpte(rap, edl, analyse)
    _controleer_herhaling(rap, edl)
    _controleer_overlays(rap, edl, pdir)

    (pdir / "review.json").write_text(
        json.dumps(rap.naar_dict(), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    return rap
