"""Fase 4 - renderen.

Leest `edl.json` en maakt er een MP4 van. Twee modi:

  preview   uit de proxies, snel, voor terugkijken tijdens het monteren
  eind      uit de bronbestanden, volledige kwaliteit

Aanpak: elk blok apart naar een tussenbestand met exact dezelfde codec,
resolutie en framerate, daarna aan elkaar plakken met de concat-demuxer.
Dat is trager dan een filter_complex met tientallen inputs, maar het is
voorspelbaar, parallelliseerbaar en het faalt niet stilletjes op een
enkele afwijkende clip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
from dataclasses import dataclass, replace
from pathlib import Path

from . import compositor, kader as kader_mod, media, paths
from .edl import EDL, OVERGANGEN, Afwerking, Canvas, Grade, Look, Overgang, VideoBlok


@dataclass
class RenderOpties:
    modus: str = "preview"  # preview | eind
    workers: int = 4
    crf: int = 20
    houd_tussenbestanden: bool = False
    # Alleen de eerste N seconden renderen. Voor snel ritme toetsen zonder
    # op de volledige montage te wachten.
    tot: float | None = None


# --------------------------------------------------------------------------
# Filterketens
# --------------------------------------------------------------------------


def _kaderexpr(blok: VideoBlok, as_: str) -> str:
    """Het kaderpunt op deze as (0..1) als ffmpeg-uitdrukking.

    Een vast punt is één getal. Keyframes worden een lineair verloop in `t`,
    van achter naar voren genest - dezelfde vorm als `_rampfilter`.

    ponytail: `t` is hier de tijd in de *bron*, want het kader wordt gesneden
    vóór de snelheidsfilters. Bij een constante snelheid is de fractie
    daardoor exact dezelfde als in de speler (bron en uitvoer lopen in
    verhouding mee); bij een speed-ramp wijkt hij er iets van af. Keyframes op
    een ramp-shot bestaan nog niet - wie ze maakt, verlegt dit naar na
    `setpts`.
    """
    punten = (blok.kader or {}).get("punten")
    if not punten:
        punt = kader_mod.punt_op(blok.kader)
        return f"{punt[0 if as_ == 'x' else 1]:.6f}"

    rij = [(float(p["t"]), float(p.get(as_, kader_mod.MIDDEN))) for p in punten]
    duur = max(1e-3, blok.bron_lengte)
    expr = f"{rij[-1][1]:.6f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(rij, rij[1:]))):
        a, z = t0 * duur, t1 * duur
        helling = (v1 - v0) / max(1e-6, z - a)
        expr = (
            f"if(lt(t\\,{z:.5f})\\,{v0:.6f}+(t-{a:.5f})*{helling:.6f}\\,{expr})"
        )
    if rij[0][0] > 0:
        expr = f"if(lt(t\\,{rij[0][0] * duur:.5f})\\,{rij[0][1]:.6f}\\,{expr})"
    return expr


def _kadercrop(blok: VideoBlok, b: int, h: int) -> str:
    """De crop die het canvas uit de bron haalt, rond het kaderpunt.

    Zonder kader staat hij in het midden, precies zoals `crop=b:h` altijd
    deed. Mét kader schuift hij mee met het onderwerp, geklemd binnen het
    beeld - buiten de bron croppen geeft een zwarte rand.

    Dit is stap 1 van de twee die `cve/kader.py` beschrijft; `_zoomfilter`
    doet stap 2 binnen dit venster. De speler rekent dezelfde twee stappen in
    `kaderVul()`.
    """
    if not blok.kader:
        return f"crop={b}:{h}"
    return (
        f"crop={b}:{h}"
        f":x=clip(iw*({_kaderexpr(blok, 'x')})-ow/2\\,0\\,iw-ow)"
        f":y=clip(ih*({_kaderexpr(blok, 'y')})-oh/2\\,0\\,ih-oh)"
    )


def _pasfilter(blok: VideoBlok, canvas: Canvas) -> str:
    """Zet het beeld op canvasformaat volgens de vulmodus van het blok."""
    b, h = canvas.breedte, canvas.hoogte

    if blok.vulmodus == "vul":
        # Vergroot tot beide zijden gedekt zijn, snijd het teveel weg.
        return (
            f"scale={b}:{h}:force_original_aspect_ratio=increase:flags=bicubic,"
            + _kadercrop(blok, b, h)
        )

    if blok.vulmodus == "pas":
        return (
            f"scale={b}:{h}:force_original_aspect_ratio=decrease:flags=bicubic,"
            f"pad={b}:{h}:(ow-iw)/2:(oh-ih)/2:black"
        )

    # wazig: het beeld past in het midden, met een uitvergrote wazige versie
    # van zichzelf als achtergrond. Ziet er stukken beter uit dan zwarte balken.
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={b}:{h}:force_original_aspect_ratio=increase,crop={b}:{h},"
        f"gblur=sigma=28," + ",".join(
            _kleurfilter(helderheid=-0.10, verzadiging=0.85)
        ) + "[bgb];"
        f"[fg]scale={b}:{h}:force_original_aspect_ratio=decrease:flags=bicubic[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
    )


def _kleurfilter(*, contrast: float = 1.0, verzadiging: float = 1.0,
                 helderheid: float = 0.0) -> list[str]:
    """Contrast, helderheid en verzadiging — zonder `eq`.

    **`eq` is een GPL-filter.** De LGPL-ffmpeg die met de app meegaat heeft
    hem niet, en dan faalt de render met "Filter not found" — pas zichtbaar
    sinds de meegeleverde ffmpeg vóór die van het systeem gaat. `lutyuv` doet
    contrast en helderheid op de luma (precies waar `eq` ze ook op doet) en
    `hue=s=` de verzadiging; beide zitten in de LGPL-bouw.
    """
    delen = []
    if contrast != 1.0 or helderheid != 0.0:
        delen.append(
            f"lutyuv=y='clip((val-128)*{contrast:.3f}+128+{helderheid * 255:.1f},16,235)'"
        )
    if verzadiging != 1.0:
        delen.append(f"hue=s={verzadiging:.3f}")
    return delen


def _gradefilter(g: Grade) -> str:
    """Kleurbewerking. Warmte via kleurbalans, de rest via luma en hue."""
    delen = _kleurfilter(
        contrast=g.contrast, verzadiging=g.verzadiging, helderheid=g.helderheid
    )
    if abs(g.warmte) > 0.001:
        rood = 0.12 * g.warmte
        blauw = -0.12 * g.warmte
        delen.append(f"colorbalance=rm={rood:.3f}:bm={blauw:.3f}")
    return ",".join(delen)


def _zoomfilter(blok: VideoBlok, canvas: Canvas, fps: int, vast: bool = False) -> str:
    """Ken Burns: langzaam bewegen binnen het beeld.

    In- en uitzoomen gaat met `zoompan`. Dat moet ook: een `crop` waarvan de
    breedte of hoogte per frame verandert levert een stroom met wisselende
    afmetingen op, en daar loopt de encoder op vast (VideoToolbox geeft
    "Invalid argument"). `zoompan` levert altijd hetzelfde formaat.

    Schuiven kan wel met een crop, want daar verandert alleen de positie.
    """
    if blok.zoom == "geen" or blok.zoom_kracht <= 0:
        return ""

    k = max(0.02, min(0.6, blok.zoom_kracht))
    b, h = canvas.breedte, canvas.hoogte
    n = max(2, int(round(blok.duur * fps)))
    # `vast`: de beweging staat stil in haar eindstand. Zo houdt de speler een
    # blok vast dat tijdens een overgang doorloopt (kenBurns() klemt op 1), en
    # zo moet de staart van dat blok in de export er dus ook uitzien.
    voortgang = "1" if vast else f"on/{n}"

    if blok.zoom in ("in", "uit"):
        z = (
            f"1+{k:.4f}*{voortgang}" if blok.zoom == "in"
            else f"1+{k:.4f}-{k:.4f}*{voortgang}"
        )
        # Vooraf opschalen: zoompan rekent op de invoer, en zonder extra
        # pixels wordt een inzoom zichtbaar zachter.
        groot_b, groot_h = (int(b * 1.6) // 2) * 2, (int(h * 1.6) // 2) * 2
        return (
            f"scale={groot_b}:{groot_h}:flags=bicubic,"
            f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={b}x{h}:fps={fps}"
        )

    groot_b, groot_h = (int(b * (1 + k)) // 2) * 2, (int(h * (1 + k)) // 2) * 2
    sx, sy = groot_b - b, groot_h - h
    duur = max(0.1, blok.duur)
    f = "1" if vast else f"t/{duur:.4f}"
    beweging = {
        "links": (f"'({sx})*(1-{f})'", f"{sy // 2}"),
        "rechts": (f"'({sx})*({f})'", f"{sy // 2}"),
        "omhoog": (f"{sx // 2}", f"'({sy})*(1-{f})'"),
        "omlaag": (f"{sx // 2}", f"'({sy})*({f})'"),
    }.get(blok.zoom)
    if not beweging:
        return ""
    x, y = beweging
    return f"scale={groot_b}:{groot_h}:flags=bicubic,crop=w={b}:h={h}:x={x}:y={y}"


# --------------------------------------------------------------------------
# Look en afwerking
# --------------------------------------------------------------------------
#
# Alles hier draait op de LGPL-ffmpeg die met de app meegaat: `lut3d`, `noise`,
# `vignette`, `gblur`, `blend`, `colorchannelmixer`, `lutrgb`, `negate`,
# `rgbashift`, `crop` en `pad`. Alle tien zijn nagelopen met
# `ffmpeg -filters`; `eq` zit er niet in en komt hier dus ook niet voor.
#
# De hele keten rekent in **gbrp** en niet in yuv420p. Dat is geen smaak: een
# `blend=all_mode=screen` op de U- en V-vlakken van yuv rekent met waarden die
# rond 128 draaien, en dan verschuift de kleur in plaats van dat het licht
# oplicht. In RGB doet screen wat het hoort te doen.


def _ffmpeg_pad(pad: Path) -> str:
    """Een bestandspad als filterargument, door beide parsers van ffmpeg heen.

    ffmpeg leest een filterketen in twee lagen, elk met zijn eigen speciale
    tekens en zijn eigen backslash:

    1. de optieparser van één filter knipt op `:` en kent `'` als aanhalingsteken;
    2. de ketenparser knipt op `,` `;` `[` `]` en kent `'` ook.

    Een teken dat in laag 1 ontsnapt moet, gaat er dus twee keer langs:
    `C:/looks` wordt `C\\\\:/looks`. Een apostrof en een komma — "José O'Neil",
    "Film, deel 2" — struikelen alleen over laag 2. Zonder dit weigerde ffmpeg
    de hele keten met "No option name near"; gemeten 03-10-2026.

    Er komt geen shell aan te pas (`subprocess` met een lijst), dus de
    backslashes horen er letterlijk in.
    """
    tekst = pad.as_posix()
    for laag in (("\\", ":", "'"), ("\\", "'", ",", ";", "[", "]")):
        # De backslash als eerste: anders ontsnapt hij de backslashes die
        # dezelfde ronde er net zelf bij gezet heeft.
        for teken in laag:
            tekst = tekst.replace(teken, "\\" + teken)
    return tekst


def _meng(tak: str, modus: str, dekking: float, naam: str) -> str:
    """Eén tak naast het origineel zetten en er met `blend` over mengen.

    Dit is het hele sterkte-mechanisme: `dekking` is de weegfactor tussen het
    beeld zoals het was en het beeld na `tak`. 1,0 is de volle tak, 0,0 het
    origineel.

    Welke invoer boven moet, hangt af van de modus — en dat is precies waar
    het op 03-10-2026 op misging. `blend` weegt `all_opacity` bij modus
    `normal` naar de BOVENSTE laag (`boven*o + onder*(1-o)`), maar bij elke
    andere modus naar het resultaat van de blend (`boven + (blend-boven)*o`).
    Eén vaste volgorde kan die twee dus niet allebei goed hebben: met de tak
    onderaan betekende sterkte 1,00 bij een LUT juist "origineel".
    """
    a, b, c = f"{naam}a", f"{naam}b", f"{naam}c"
    boven, onder = (c, a) if modus == "normal" else (a, c)
    return (
        f"split=2[{a}][{b}];[{b}]{tak}[{c}];"
        f"[{boven}][{onder}]blend=all_mode={modus}:all_opacity={dekking:.4f}"
    )


def _hooglichten(grens: int) -> str:
    """Alleen wat helderder is dan `grens` overhouden, de rest op zwart.

    Gloed en halation komen in het echt uit de hooglichten. Zonder deze stap
    licht een heel beeld op en ziet het eruit als een waas over de lens.
    """
    expr = f"'if(gt(val,{grens}),val,0)'"
    return f"lutrgb=r={expr}:g={expr}:b={expr}"


def _lookfilter(look: Look, afw: Afwerking, canvas: Canvas, seed: int = 0) -> str:
    """De look en de afwerking als één stuk filterketen, of "" als er niets is.

    De volgorde is niet willekeurig: eerst de kleur (de LUT), dan het licht
    (gloed, halation, lichtlek), dan het materiaal (korrel, vignet, kleurrand),
    dan de camera (filmtrilling) en als laatste de balken. Breedbeeld hoort
    achteraan omdat korrel en vignet niet op zwarte balken thuishoren, en de
    trilling ervoor omdat balken niet mogen meebewegen.
    """
    from . import looks as lookcatalogus

    # Met de vlag aan doet de native compositor de hele look na het plakken
    # (zie `compositor.pas_toe`); hier hoort dan niets meer te gebeuren.
    if compositor.aan():
        return ""

    h, b = canvas.hoogte, canvas.breedte
    stappen: list[str] = []

    lut = lookcatalogus.lut_pad(look.id)
    sterkte = max(0.0, min(1.0, look.sterkte))
    if lut is not None and sterkte > 0:
        tak = f"lut3d=file={_ffmpeg_pad(lut)}:interp=tetrahedral"
        stappen.append(tak if sterkte >= 0.999 else _meng(tak, "normal", sterkte, "lut"))

    if afw.gloed > 0:
        # Sigma in een fractie van de beeldhoogte, niet in pixels: anders is de
        # gloed op een 540p-proxy twee keer zo breed als op de export (§4.4).
        sigma = max(1.0, 0.012 * h)
        stappen.append(
            _meng(
                f"{_hooglichten(185)},gblur=sigma={sigma:.2f}",
                "screen", 0.75 * afw.gloed, "glo",
            )
        )

    if afw.halation > 0:
        sigma = max(2.0, 0.024 * h)
        stappen.append(
            _meng(
                f"{_hooglichten(205)},gblur=sigma={sigma:.2f},"
                f"colorchannelmixer=rr=1:gg=0.30:bb=0.10",
                "screen", 0.85 * afw.halation, "hal",
            )
        )

    if afw.lichtlek > 0:
        # Een zachte warme gradiënt uit de linkerbovenhoek. `vignette` met zijn
        # middelpunt ín die hoek geeft precies dat verloop; zwaar uitvegen
        # haalt de beeldinhoud eruit zodat er een wash overblijft.
        # ponytail: één vaste hoek, geen draaiende lek. Richting instelbaar
        # maken kan als iemand erom vraagt.
        sigma = max(4.0, 0.06 * h)
        stappen.append(
            _meng(
                f"vignette=x0=0:y0=0:angle={1.2:.2f},gblur=sigma={sigma:.2f},"
                f"colorchannelmixer=rr=1:gg=0.58:bb=0.22",
                "screen", 0.55 * afw.lichtlek, "lek",
            )
        )

    if afw.korrel > 0:
        # Vaste seed, `t` voor korrel die per frame verandert en `u` voor een
        # gelijkmatige verdeling. Deterministisch: dezelfde seed en hetzelfde
        # frame geven dezelfde korrel, in de voorvertoning en in de export.
        kracht = max(1, round(2 + 22 * afw.korrel))
        stappen.append(f"noise=all_seed={seed}:alls={kracht}:allf=t+u")

    if afw.vignet > 0:
        stappen.append(f"vignette=angle={0.20 + 1.00 * afw.vignet:.4f}")

    if afw.kleurrand > 0:
        px = max(1, round(0.0015 * b * afw.kleurrand))
        stappen.append(f"rgbashift=rh={px}:bh=-{px}")

    if afw.filmtrilling > 0:
        # Geen `random()`: die is in een ffmpeg-expressie niet te zaaien en dan
        # zijn twee renders niet gelijk. Twee sinussen met onderling
        # onvergelijkbare perioden zien net zo onrustig uit en zijn exact
        # herhaalbaar. `n` begint op 0 omdat `_blokfilter` eerst trimt.
        # Geen `:eval=frame`: die optie heeft `crop` niet — hij herrekent zijn
        # x en y altijd per frame. Met `eval` erin faalt de hele render met
        # "Option not found".
        amp = max(1, round(0.003 * h * afw.filmtrilling))
        gb, gh = b + 2 * amp, h + 2 * amp
        fx, fy = 1.9 + (seed % 7) * 0.11, 1.31 + (seed % 5) * 0.09
        stappen.append(
            f"scale={gb}:{gh}:flags=bicubic,"
            f"crop=w={b}:h={h}"
            f":x='{amp}+{amp}*sin(n*{fx:.4f})'"
            f":y='{amp}+{amp}*sin(n*{fy:.4f})'"
        )

    if afw.breedbeeld > 0:
        doel = (int(b / 2.39) // 2) * 2
        if 0 < doel < h:
            stappen.append(
                f"crop={b}:{doel},pad={b}:{h}:0:{(h - doel) // 2}:black"
            )

    if not stappen:
        return ""
    return "format=gbrp," + ",".join(stappen)


def voorbeeldfilter(
    look: Look, afw: Afwerking, canvas: Canvas, *, aanloop: float = 0.0,
    breedte: int = 0, seed: int = 0, uitvoer: str = "yuv420p",
) -> str:
    """De keten voor één voorbeeldframe — dezelfde als de render gebruikt.

    `looks.voorbeeld()` roept dit aan. Hier staat geen tweede implementatie:
    `_pasfilter` en `_lookfilter` zijn letterlijk dezelfde functies die
    `_blokfilter` gebruikt. Dat is wat "voorvertoning = export" hier betekent.

    `uitvoer="rgba"` is wat de compositor-weg vraagt: dan levert ffmpeg alleen
    het gekaderde beeld en doet de compositor de kleur. Niet yuv420p als
    tussenstap — dat halveert de chroma vóór de LUT eraan komt.
    """
    nep = VideoBlok(id="voorbeeld", clip="", bestand="", bron_start=0.0,
                    duur=1.0, tijdlijn_start=0.0, vulmodus="vul")
    delen: list[str] = []
    if aanloop > 0:
        delen.append(f"trim=start={aanloop:.3f}")
    delen.append("setpts=PTS-STARTPTS")
    delen.append(_pasfilter(nep, canvas))
    kleur = _lookfilter(look, afw, canvas, seed)
    if kleur:
        delen.append(kleur)
    delen.append(f"format={uitvoer}")
    if breedte > 0:
        delen.append(f"scale={breedte}:-2:flags=bicubic")
    return ",".join(delen)



def _rampfilter(blok: VideoBlok) -> str:
    """Speed-ramp als één `setpts`: brontijd T -> uitvoertijd, stuk voor stuk.

    Elk stuk uit `snelheid_stukken()` heeft een constante snelheid. Voor een
    bronframe op T zoeken we het stuk waar T in valt en rekenen terug naar de
    uitvoertijd. Daarna maakt `fps=` er weer een vast rooster van (bij
    slow-motion herhaalt het frames, bij versnellen laat het ze vallen).
    """
    stukken = blok.snelheid_stukken()
    bron = [0.0]
    uit = [0.0]
    for d, v in stukken:
        bron.append(bron[-1] + d * v)
        uit.append(uit[-1] + d)
    # Van achter naar voren nesten; het laatste stuk loopt door tot het eind.
    k = len(stukken) - 1
    expr = f"{uit[k]:.5f}+(T-{bron[k]:.5f})/{stukken[k][1]:.5f}"
    for k in range(len(stukken) - 2, -1, -1):
        expr = (
            f"if(lt(T\\,{bron[k + 1]:.5f})\\,"
            f"{uit[k]:.5f}+(T-{bron[k]:.5f})/{stukken[k][1]:.5f}\\,{expr})"
        )
    return f"setpts=({expr})/TB"

def _blokfilter(blok: VideoBlok, edl: EDL, aanloop: float = 0.0, staart: bool = False) -> str:
    """De hele filterketen voor een blok, met `t` gegarandeerd op 0 aan het begin.

    Dat eerste `trim` is geen detail. Het grove springen naar het keyframe
    gebeurt met `-ss` vóór `-i`; de rest van de aanloop moet er hier af en
    niet met een tweede `-ss` ná `-i`. Een `-ss` aan de uitvoerkant gooit
    namelijk frames weg *nadat* de filters gedraaid hebben: de pan en de
    dip-naar-zwart speelden zich dan af in precies die twee seconden die
    daarna in de prullenbak gingen.

    Wat je zag: een pan die na twee seconden stilviel (de crop-expressie was
    op zijn eindwaarde aangekomen en werd daar vastgeklemd) en een dip naar
    zwart die helemaal niet te zien was. Zoom in en uit hadden er geen last
    van, want `zoompan` rekent met `on` - het uitvoerframenummer - en dat
    begint altijd op 0. Vandaar dat dit maandenlang onopgemerkt bleef.
    """
    delen: list[str] = []
    if aanloop > 0:
        delen.append(f"trim=start={aanloop:.3f}")
    delen.append("setpts=PTS-STARTPTS")
    delen.append(_pasfilter(blok, edl.canvas))

    zoom = _zoomfilter(blok, edl.canvas, edl.canvas.fps, vast=staart)
    if zoom:
        delen.append(zoom)

    grade = _gradefilter(edl.grade)
    if grade:
        delen.append(grade)

    if blok.snelheid_verloop:
        delen.append(_rampfilter(blok))
    elif blok.snelheid != 1.0:
        delen.append(f"setpts={1.0 / blok.snelheid:.5f}*PTS")

    delen.append(f"fps={edl.canvas.fps}")
    if blok.snelheid_verloop or blok.snelheid != 1.0 or staart:
        # Bij een andere snelheid kan het laatste bronframe op een tijdstip
        # vallen dat `fps=` net niet meer uitgeeft: dan levert ffmpeg 119 van
        # de 120 frames en schuift elke volgende snede een frame naar voren.
        # Een paar klonen van het laatste beeld; `-frames:v` knipt de rest af.
        #
        # Een staart begint op `bron_eind` van A: daar kan nog maar een fractie
        # van een seconde bron over zijn, en dan zijn drie klonen te weinig.
        # `stop=-1` kloont onbeperkt; `-frames:v n` bepaalt waar het stopt.
        delen.append("tpad=stop_mode=clone:stop=" + ("-1" if staart else "3"))

    # Look en afwerking ná `fps=`: de filmtrilling rekent met `n`, het
    # uitvoerframenummer, en dat moet hetzelfde rooster volgen als `-frames:v`.
    kleurlook = _lookfilter(edl.look, edl.afwerking, edl.canvas, edl.effectseed)
    if kleurlook:
        delen.append(kleurlook)

    # Bevriezen zit niet in deze keten: het stilstaande deel wordt een eigen
    # bestand dat meegeconcat wordt (zie `_frameverdeling` en `_render_stil`).
    # Via een filter lukte het niet - `tpad=stop_mode=clone` kreeg zijn
    # gekloonde frames er in geen enkele vorm doorheen.

    delen.append("format=yuv420p")

    # Overgang aan het begin van het blok. Met de compositor doet die de
    # overgang (alle veertien, met dezelfde shader als de speler); dit is de
    # oude terugval voor als hij er niet is.
    over = blok.overgang_in
    if compositor.aan():
        pass
    elif over.soort == "dip_zwart" and over.duur > 0:
        delen.append(f"fade=t=in:st=0:d={over.duur:.3f}:color=black")
    elif over.soort == "dip_wit" and over.duur > 0:
        delen.append(f"fade=t=in:st=0:d={over.duur:.3f}:color=white")
    elif over.soort == "crossfade" and over.duur > 0:
        # Zonder overlappende blokken kan een echte crossfade niet; een korte
        # in-fade geeft hetzelfde gevoel zonder de tijdlijn te verschuiven.
        delen.append(f"fade=t=in:st=0:d={over.duur:.3f}")

    return ",".join(delen)


# --------------------------------------------------------------------------
# Renderen
# --------------------------------------------------------------------------


def _frameverdeling(blok: VideoBlok, fps: int) -> tuple[int, int]:
    """Hoeveel frames bewegen er, en hoeveel staan er stil.

    De som is altijd exact het frameaantal van het blok. Daar hangt de hele
    montage aan: wijkt die af, dan schuift alles erna van de beat af.
    """
    totaal = max(1, blok.frames or round(blok.duur * fps))
    if blok.bevriezen <= 0:
        return totaal, 0
    # Minstens één bewegend frame overhouden - daar komt het stilstaande beeld
    # uit, en een blok van nul frames laat ffmpeg niets opleveren.
    stil = min(totaal - 1, max(1, round(blok.bevriezen * fps)))
    return totaal - stil, max(0, stil)


def _laatste_frame(bron: Path, doel: Path) -> Path:
    """Trek het laatste frame van een gerenderd blok als PNG.

    `-sseof` springt naar het einde; zonder `-frames:v` overschrijft `-update 1`
    net zo lang tot het laatste frame overblijft. Dat is betrouwbaarder dan
    rekenen met een tijdstip, want dat valt zelden precies op een frame.
    """
    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-sseof", "-0.5",
            "-i", str(bron),
            "-update", "1",
            "-q:v", "1",
            str(doel),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return doel



def _encoder_voor(
    opties: "RenderOpties", breedte: int, hoogte: int, fps: float
) -> tuple[str, list[str]]:
    """Encoder plus instellingen die bij de modus en de beeldgrootte passen.

    libx264 werkt op kwaliteit (crf). De hardware-encoders werken op bitrate,
    en een vaste 8 Mbit/s is voor 1080p prima maar voor 4K blokkerig. Voor de
    eindexport schaalt de bitrate daarom mee met pixels per seconde
    (0,15 bit per pixel: 1080p30 ≈ 9 Mbit/s, 4K30 ≈ 37 Mbit/s).
    """
    encoder, enc_opties = media.video_encoder()
    if encoder == "libx264":
        return encoder, ["-preset", "medium" if opties.modus == "eind" else "veryfast",
                         "-crf", str(opties.crf)]
    if opties.modus == "eind" and "-b:v" in enc_opties:
        bps = max(8_000_000, int(breedte * hoogte * fps * 0.15))
        enc_opties = list(enc_opties)
        enc_opties[enc_opties.index("-b:v") + 1] = str(bps)
    return encoder, enc_opties

def _render_stil(
    frame: Path, aantal: int, canvas: Canvas, doel: Path, opties: RenderOpties
) -> Path:
    """Een stilstaand blok van `aantal` frames uit één PNG.

    Alles moet gelijk zijn aan de bewegende blokken - encoder, resolutie,
    framerate, pixelformaat en tijdschaal - anders weigert de concat-demuxer
    de stroom of loopt het geluid uit de pas.
    """
    encoder, enc_opties = _encoder_voor(opties, canvas.breedte, canvas.hoogte, canvas.fps)

    cmd = [
        str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1",
        "-framerate", str(canvas.fps),
        "-i", str(frame),
        "-frames:v", str(max(1, aantal)),
        "-vf", f"scale={canvas.breedte}:{canvas.hoogte},fps={canvas.fps},format=yuv420p",
        "-c:v", encoder,
        *enc_opties,
        "-pix_fmt", "yuv420p",
        "-video_track_timescale", str(canvas.fps * 1000),
        str(doel),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        laatste = (r.stderr or "").strip().splitlines()[-3:]
        raise media.MediaFout(f"Stilstaand blok faalde: {' | '.join(laatste)}")
    return doel


def _render_blok(
    blok: VideoBlok,
    edl: EDL,
    bronmap: Path,
    proxymap: Path,
    doelmap: Path,
    opties: RenderOpties,
    staart: bool = False,
) -> list[Path]:
    if opties.modus == "eind":
        bron = bronmap / blok.bestand
    else:
        bron = proxymap / f"{blok.clip}.mp4"
        if not bron.exists():
            bron = bronmap / blok.bestand

    doel = doelmap / f"{blok.id}.mp4"
    beweeg_frames, stil_frames = _frameverdeling(blok, edl.canvas.fps)
    encoder, enc_opties = _encoder_voor(
        opties, edl.canvas.breedte, edl.canvas.hoogte, edl.canvas.fps
    )

    cmd = [
        str(paths.ffmpeg()),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-hwaccel",
        "auto",
        # -ss voor -i is snel: springen naar het dichtstbijzijnde keyframe.
        # De rest van de aanloop gaat er in de filterketen af (`trim`), niet
        # met een tweede -ss - zie de uitleg bij `_blokfilter`.
        "-ss",
        f"{max(0.0, blok.bron_start - 2.0):.3f}",
        "-i",
        str(bron),
        # Exact aantal frames, niet `-t <seconden>`. Met -t rondt ffmpeg af en
        # levert een blok soms een frame te veel of te weinig; over tientallen
        # blokken loopt de montage dan uit de pas met de EDL.
        "-frames:v",
        str(beweeg_frames),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        _blokfilter(blok, edl, aanloop=min(2.0, blok.bron_start), staart=staart),
        "-c:v",
        encoder,
        *enc_opties,
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        str(edl.canvas.fps * 1000),
        str(doel),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        laatste = (r.stderr or "").strip().splitlines()[-3:]
        raise media.MediaFout(f"Blok {blok.id} ({blok.bestand}) faalde: {' | '.join(laatste)}")

    if stil_frames <= 0:
        return [doel]

    frame = _laatste_frame(doel, doelmap / f"{blok.id}-laatste.png")
    stil = _render_stil(
        frame, stil_frames, edl.canvas, doelmap / f"{blok.id}-stil.mp4", opties
    )
    return [doel, stil]



def _staart_precies(
    delen: list[Path], n: int, laatste_van_a: Path, edl: EDL, werk: Path,
    opties: RenderOpties, naam: str,
) -> list[Path]:
    """Vul een te korte staart aan tot precies `n` frames.

    De compositor leest `staarten.mp4` als één doorlopende stroom en pakt per
    overgang `n` frames; hij kent de grens tussen twee staarten niet. Levert
    één staart er minder, dan eet hij de frames van de volgende op en toont
    elke overgang daarna het verkeerde beeld - of de export breekt af.

    Te kort komt het als blok A tegen het einde van zijn bron eindigt: na de
    seek naar `bron_eind` is er niets meer om door te laten lopen. `tpad`
    kloont dan het laatste bronframe, maar zonder ook maar één bronframe
    levert ffmpeg een leeg bestand. Dan nemen we het laatste gerenderde beeld
    van A zelf.
    """
    goed = [(p, media.frames_in(p)) for p in delen]
    paden = [p for p, k in goed if k > 0]
    echt = sum(k for _, k in goed)
    if echt >= n:
        return paden
    beeld = _laatste_frame(paden[-1] if paden else laatste_van_a, werk / f"{naam}-vul.png")
    paden.append(
        _render_stil(beeld, n - echt, edl.canvas, werk / f"{naam}-vul.mp4", opties)
    )
    return paden


def _overgangen(
    blokken: list[VideoBlok], edl: EDL, bronmap: Path, proxymap: Path, werk: Path,
    opties: RenderOpties, delen: dict[str, list[Path]],
) -> tuple[list[dict], Path | None]:
    """Overgangen voor de compositor: waar ze zitten, en de staarten van A.

    Precies wat de speler doet (`Speler.tsx`): de overgang zit aan het begin
    van blok B en duurt `overgang_in.duur` seconden. In die tijd loopt blok A
    door — verder in de bron, met zijn Ken Burns stil in de eindstand. Die
    doorloop bestaat in de export niet vanzelf, dus renderen we hem apart als
    "staart" en mengt de compositor hem met de kop van B. De tijdlijn verandert
    niet: B begint op hetzelfde frame, alleen zijn eerste frames zijn gemengd.
    """
    fps = edl.canvas.fps
    lijst: list[dict] = []
    staarten: list[Path] = []
    start = 0
    vorige: VideoBlok | None = None
    for b in blokken:
        frames_b = max(1, b.frames or round(b.duur * fps))
        over = b.overgang_in
        if vorige is not None and over.soort != "snede" and over.duur > 0:
            duur = over.duur * fps
            n = min(frames_b, max(1, math.ceil(duur - 1e-6)))
            a = vorige
            if a.bevriezen > 0:
                # A stond al stil; dan blijft hij dat ook in de staart.
                beeld = _laatste_frame(delen[a.id][-1], werk / f"{a.id}-staart.png")
                staarten.append(_render_stil(beeld, n, edl.canvas, werk / f"{a.id}-staart.mp4", opties))
            else:
                eind = a.snelheid_stukken()[-1][1]
                verder = replace(
                    a, id=f"{a.id}-staart", bron_start=a.bron_eind, duur=round(n / fps, 6),
                    tijdlijn_start=a.tijdlijn_eind, frames=n, snelheid=eind,
                    snelheid_verloop=[], bevriezen=0.0, overgang_in=Overgang(),
                )
                deel = _render_blok(verder, edl, bronmap, proxymap, werk, opties, staart=True)
                staarten += _staart_precies(
                    deel, n, delen[a.id][-1], edl, werk, opties, f"{a.id}-staart"
                )
            lijst.append({
                "start": start, "n": n, "duur": round(duur, 6),
                "soort": OVERGANGEN.index(over.soort),
            })
        start += frames_b
        vorige = b
    if not lijst:
        return [], None
    return lijst, _plak(staarten, werk / "staarten.mp4", fps)

def _plak(delen: list[Path], doel: Path, fps: int) -> Path:
    lijst = doel.parent / "concat.txt"
    lijst.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in delen) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [
            str(paths.ffmpeg()),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lijst),
            "-c",
            "copy",
            str(doel),
        ],
        check=True,
        capture_output=True,
        timeout=1800,
    )
    return doel


def _duck_uitdrukking(edl: EDL, projectmap: Path, sterkte: float = 0.28) -> str:
    """Zet de muziek zachter waar gesproken wordt.

    De momenten komen uit `ondertitels.json` — daar staat per regel wanneer er
    gepraat wordt. Zonder ondertitels gebeurt er niets, en dat is prima: dan
    valt er ook niets te ducken.
    """
    pad = projectmap / "ondertitels.json"
    if not pad.exists():
        return ""
    try:
        regels = json.loads(pad.read_text(encoding="utf-8")).get("regels", [])
    except (json.JSONDecodeError, OSError):
        return ""
    if not regels:
        return ""

    # Vensters samenvoegen die dicht op elkaar liggen, met 0,35 s aanloop en
    # uitloop zodat het zakken en stijgen niet hoorbaar hakkelt.
    marge = 0.35
    vensters: list[list[float]] = []
    for r in regels:
        a, b = max(0.0, r["start"] - marge), r["eind"] + marge
        if vensters and a <= vensters[-1][1] + 0.2:
            vensters[-1][1] = max(vensters[-1][1], b)
        else:
            vensters.append([a, b])

    voorwaarden = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in vensters)
    return f"volume=volume='if({voorwaarden},{sterkte:.2f},1)':eval=frame"


def _clipgeluid(edl: EDL, bronmap: Path) -> tuple[list[str], list[str], list[str]]:
    """Invoer, filters en labels voor blokken die hun eigen geluid meebrengen.

    Hiermee werken J- en L-cuts: het geluid mag eerder beginnen of later
    doorlopen dan het beeld.
    """
    invoer: list[str] = []
    filters: list[str] = []
    labels: list[str] = []

    for i, b in enumerate(x for x in edl.video if x.geluid > 0):
        bron = bronmap / b.bestand
        if not bron.exists():
            continue
        start = max(0.0, b.bron_start - b.geluid_voor)
        lengte = b.bron_lengte + b.geluid_voor + b.geluid_na
        op_tijdlijn = max(0.0, b.tijdlijn_start - b.geluid_voor)
        idx = len(labels) + 2  # 0 = beeld, 1 = muziek

        invoer += ["-ss", f"{start:.3f}", "-t", f"{lengte:.3f}", "-i", str(bron)]
        naam = f"c{i}"
        filters.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={b.geluid:.3f},"
            f"afade=t=in:st=0:d=0.08,"
            f"afade=t=out:st={max(0.0, lengte - 0.12):.3f}:d=0.12,"
            f"adelay={int(op_tijdlijn * 1000)}|{int(op_tijdlijn * 1000)}[{naam}]"
        )
        labels.append(naam)

    return invoer, filters, labels


def _met_loudnorm(
    invoer: list[str], stappen: list[str], uit: str
) -> tuple[list[str], str]:
    """Zet de mix op de aanlevernorm: -14 LUFS, true peak onder -1 dBTP.

    Twee trappen, met opzet. `loudnorm` in een keer is een dynamische regelaar
    die tijdens het nummer nog aan het bijstellen is; het begin komt er dan
    anders uit dan het eind. Met een meetronde vooraf kent hij de hele mix en
    doet hij een enkele, vaste correctie - hoorbaar rustiger en, belangrijker,
    elke render precies hetzelfde.

    Lukt de meting niet, dan valt hij terug op een enkele trap. Beter iets
    genormaliseerd dan een montage die op +2 dBTP staat te klippen.
    """
    # Een halve dB extra marge op de true peak. loudnorm mikt op de PCM-mix,
    # maar wat de kijker hoort is AAC, en die hercodering tilt de golfvorm
    # tussen de samples net iets op. Gemeten zonder marge: doel -1,0 dBTP,
    # in het bestand -0,3 dBTP. Daarom hier -1,5 en er een harde begrenzer
    # achteraan die er geen dB doorheen laat die er niet hoort.
    tp = media.TRUE_PEAK_DOEL - 0.5
    doel = f"I={media.LUFS_DOEL}:TP={tp}:LRA={media.LRA_DOEL}"
    meting = _loudnorm_meting(invoer, stappen, uit, doel)

    if meting:
        gemeten = (
            f":measured_I={meting['input_i']}"
            f":measured_TP={meting['input_tp']}"
            f":measured_LRA={meting['input_lra']}"
            f":measured_thresh={meting['input_thresh']}"
            f":offset={meting['target_offset']}:linear=true"
        )
    else:
        gemeten = ""

    # loudnorm rekent intern op 192 kHz; zonder resample eindigt het spoor daar
    # ook op en dat wil de AAC-encoder niet.
    plafond = 10 ** (media.TRUE_PEAK_DOEL / 20.0)
    stappen = [
        *stappen,
        f"{uit}loudnorm={doel}{gemeten},aresample=48000,"
        f"alimiter=limit={plafond:.4f}:level=disabled[genorm]",
    ]
    return stappen, "[genorm]"


def _loudnorm_meting(
    invoer: list[str], stappen: list[str], uit: str, doel: str
) -> dict[str, str] | None:
    cmd = [
        str(paths.ffmpeg()), "-hide_banner", "-v", "info", "-nostats",
        *invoer,
        "-filter_complex", ";".join([*stappen, f"{uit}loudnorm={doel}:print_format=json[q]"]),
        "-map", "[q]", "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError):
        return None
    tekst = (r.stdout or "") + (r.stderr or "")
    # De JSON staat als laatste blok in het log.
    haakje = tekst.rfind("{")
    if haakje < 0:
        return None
    try:
        d = json.loads(tekst[haakje : tekst.rfind("}") + 1])
    except json.JSONDecodeError:
        return None
    nodig = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if not all(k in d for k in nodig):
        return None
    # Bij een (bijna) stil spoor geeft loudnorm -inf terug; daar valt niets
    # mee te rekenen.
    if any("inf" in str(d[k]) for k in nodig):
        return None
    return d


def _muziek_eronder(stil: Path, edl: EDL, muziekmap: Path, doel: Path,
                    projectmap: Path | None = None) -> Path:
    if not edl.audio:
        shutil.copy2(stil, doel)
        return doel

    spoor = edl.audio[0]
    bron = muziekmap / spoor.bestand
    if not bron.exists():
        shutil.copy2(stil, doel)
        return doel

    # De duur van het beeld, niet van de EDL: bij een snelle voorvertoning is
    # het beeld korter en moet de muziek daar netjes op uitfaden.
    duur = media.probe(stil).duur or edl.duur
    fade_start = max(0.0, duur - spoor.fade_out)

    duck = _duck_uitdrukking(edl, projectmap) if projectmap else ""
    muziek = (
        f"[1:a]atrim=start={spoor.bron_start:.3f}:duration={duur:.3f},"
        f"asetpts=PTS-STARTPTS,"
        f"aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume={spoor.volume:.3f},"
        + (duck + "," if duck else "")
        + f"afade=t=in:st=0:d={max(0.05, spoor.fade_in):.3f},"
        f"afade=t=out:st={fade_start:.3f}:d={spoor.fade_out:.3f}[m]"
    )

    bronmap = (projectmap / "bronnen") if projectmap else muziekmap.parent / "bronnen"
    extra_invoer, extra_filters, extra_labels = _clipgeluid(edl, bronmap)

    stappen = [muziek, *extra_filters]
    if extra_labels:
        mix = "[m]" + "".join(f"[{n}]" for n in extra_labels)
        stappen.append(
            f"{mix}amix=inputs={len(extra_labels) + 1}:normalize=0:duration=first[a]"
        )
        uit = "[a]"
    else:
        uit = "[m]"

    invoer = ["-i", str(stil), "-i", str(bron), *extra_invoer]
    stappen, uit = _met_loudnorm(invoer, stappen, uit)

    subprocess.run(
        [
            str(paths.ffmpeg()),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *invoer,
            "-filter_complex",
            ";".join(stappen),
            "-map",
            "0:v:0",
            "-map",
            uit,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-shortest",
            "-movflags",
            "+faststart",
            str(doel),
        ],
        check=True,
        capture_output=True,
        timeout=1800,
    )
    return doel



def _overlay_encoder(edl: EDL, opties: "RenderOpties | None") -> list[str]:
    """Encoder voor de laatste pass: dezelfde kwaliteit als de blokken zelf.

    Zonder dit hercodeerde een export mét titel de hele film op de standaard
    8 Mbit/s, ook in 4K (codex-review 03-10, #11).
    """
    if opties is None:
        naam, enc = media.video_encoder()
    else:
        naam, enc = _encoder_voor(opties, edl.canvas.breedte, edl.canvas.hoogte, edl.canvas.fps)
    return [naam, *enc]

def _overlays_erover(
    basis: Path, edl: EDL, bestanden: dict[str, Path], doel: Path, frames: int = 0,
    opties: "RenderOpties | None" = None,
) -> Path:
    """Leg de transparante overlays over de montage.

    Elke overlay krijgt zijn eigen `-itsoffset` zodat hij op het juiste moment
    begint. `eof_action=pass` zorgt dat het beeld doorloopt als de overlay
    afgelopen is; `shortest=0` dat de montage niet wordt afgekapt.

    **`overlay` laat frames vallen, en niet elke keer evenveel.** Gemeten op
    dezelfde invoer: 2354, 2348, 2353 frames waar er 2361 in gingen - ook met
    een kunstmatige `color`-bron als overlay, ook met `-filter_complex_threads 1`,
    ook zonder hardware-encoder. Het is dus de framesync van het filter zelf.
    Daarom sluiten we de keten af met `fps` (vult de gaten weer op met het
    vorige beeld) en kappen we op `-frames:v` af. Dat is dezelfde aanpak als
    bij de blokken: het frameaantal is leidend, nooit de tijd.
    """
    if not bestanden:
        shutil.copy2(basis, doel)
        return doel

    blokken = [b for b in edl.overlay if b.id in bestanden]
    cmd = [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error", "-i", str(basis)]
    for b in blokken:
        cmd += ["-itsoffset", f"{b.tijdlijn_start:.3f}", "-i", str(bestanden[b.id])]

    stappen = []
    vorige = "0:v"
    for i, _ in enumerate(blokken, start=1):
        naam = f"v{i}"
        stappen.append(f"[{vorige}][{i}:v]overlay=0:0:shortest=0:eof_action=pass[{naam}]")
        vorige = naam
    stappen.append(f"[{vorige}]fps={edl.canvas.fps}[uit]")
    filter_complex = ";".join(stappen)

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[uit]",
        "-map",
        "0:a?",
        "-fps_mode",
        "cfr",
        "-frames:v",
        str(frames or round(edl.duur * edl.canvas.fps)),
        "-c:v",
        *_overlay_encoder(edl, opties),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(doel),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        laatste = (r.stderr or "").strip().splitlines()[-3:]
        raise media.MediaFout("Overlays samenstellen faalde: " + " | ".join(laatste))
    return doel


def render(
    project: str,
    *,
    opties: RenderOpties | None = None,
    log=print,
    melden=None,
    waarschuwingen: list[str] | None = None,
) -> Path:
    """Render `edl.json` naar een MP4.

    `melden(fase, klaar, totaal)` wordt bij elke stap aangeroepen, zodat de
    Studio kan laten zien wat er gebeurt. Blijft leeg als niemand kijkt.

    `waarschuwingen` is een lijst waarin dingen belanden die de video
    aantoonbaar anders maken dan bedoeld, zonder dat ze de render tegenhouden
    — titels die niet getekend konden worden, bijvoorbeeld. De app toont ze
    bij Exporteren. Geef niets mee en ze gaan alleen naar het log.
    """
    zeg = melden or (lambda *_a, **_k: None)
    opties = opties or RenderOpties()
    pdir = paths.project_dir(project)
    edl = EDL.lees(pdir / "edl.json")
    edl.valideer()

    werk = pdir / "cache" / f"render-{opties.modus}"
    if werk.exists():
        shutil.rmtree(werk)
    werk.mkdir(parents=True, exist_ok=True)

    blokken = edl.video
    if opties.tot:
        blokken = [b for b in edl.video if b.tijdlijn_start < opties.tot]
        if not blokken:
            blokken = edl.video[:1]

    encoder, _ = media.video_encoder()
    comp = compositor.info() if compositor.aan() else None
    log(
        f"Render {opties.modus}: {len(blokken)} blokken naar "
        f"{edl.canvas.breedte}x{edl.canvas.hoogte}@{edl.canvas.fps} ({encoder})"
        + (f"  ·  kleur: compositor {comp['versie']} op {comp['backend']}" if comp else "")
    )
    # Zonder compositor doet de ffmpeg-keten de look, en die is niet gelijk aan
    # wat stap Look toont. Dat hoort in het log te staan, niet stil te gebeuren.
    if (klacht := compositor.waarschuwing()):
        log(f"Let op: {klacht}")
    zeg("voorbereiden", 1, 1)

    # Per blok kunnen het er twee zijn: het bewegende deel en het bevroren
    # staartje. Vandaar een lijst per blok-id.
    delen: dict[str, list[Path]] = {}
    with ThreadPoolExecutor(max_workers=opties.workers) as pool:
        futures = {
            pool.submit(
                _render_blok, b, edl, pdir / "bronnen", pdir / "proxies", werk, opties
            ): b.id
            for b in blokken
        }
        klaar = 0
        for f in as_completed(futures):
            delen[futures[f]] = f.result()
            klaar += 1
            zeg("blokken", klaar, len(futures))
            if klaar % 5 == 0 or klaar == len(futures):
                log(f"  [{klaar}/{len(futures)}] blokken")

    volgorde = [p for b in blokken for p in delen[b.id]]
    totaal_frames = sum(
        max(1, b.frames or round(b.duur * edl.canvas.fps)) for b in blokken
    )
    zeg("samenstellen", 0, 1)
    stil = _plak(volgorde, werk / "stil.mp4", edl.canvas.fps)

    # De look achteraan in plaats van per blok. Dit is de normale weg; zonder
    # binary of met BEATCUT_COMPOSITOR=0 zit hij in de filterketen per blok.
    if compositor.aan():
        overgangen, staarten = _overgangen(
            blokken, edl, pdir / "bronnen", pdir / "proxies", werk, opties, delen
        )
        if overgangen:
            log(f"  {len(overgangen)} overgangen via de compositor")
        zeg("look", 0, 1)
        stil = compositor.pas_toe(
            stil, werk / "stil-look.mp4",
            edl.look, edl.afwerking, edl.canvas, edl.effectseed,
            encoder=_encoder_voor(
                opties, edl.canvas.breedte, edl.canvas.hoogte, edl.canvas.fps
            ),
            overgangen=overgangen, staart=staarten,
        )
        zeg("look", 1, 1)
    zeg("samenstellen", 1, 1)

    naam = f"{project}-{'snel' if opties.tot else opties.modus}.mp4"
    doel = pdir / "renders" / naam
    doel.parent.mkdir(parents=True, exist_ok=True)

    zeg("geluid", 0, 1)
    met_geluid = _muziek_eronder(
        stil, edl, pdir / "muziek", werk / "met-geluid.mp4", projectmap=pdir
    )
    zeg("geluid", 1, 1)

    # Motion graphics als laatste laag: die horen over de kleurbewerking heen,
    # niet eronder.
    overlays: dict[str, Path] = {}
    if edl.overlay and not opties.tot:
        from .graphics import render_alle

        zeg("titels", 0, max(1, len(edl.overlay)))
        try:
            overlays = render_alle(edl, pdir, log=log, waarschuwingen=waarschuwingen)
        except Exception as e:  # noqa: BLE001
            log(f"Motion graphics overgeslagen: {e}")
            if waarschuwingen is not None:
                waarschuwingen.append(
                    f"De {len(edl.overlay)} titel(s) staan niet in de video: {e}"
                )
    zeg("titels", max(1, len(edl.overlay)), max(1, len(edl.overlay)))
    _overlays_erover(met_geluid, edl, overlays, doel, frames=totaal_frames, opties=opties)

    if not opties.houd_tussenbestanden:
        shutil.rmtree(werk, ignore_errors=True)

    info = media.probe(doel)
    log(
        f"\nKlaar: {doel}\n"
        f"{info.duur:.1f}s  ·  {info.breedte}x{info.hoogte}  ·  "
        f"{doel.stat().st_size / 1_000_000:.1f} MB"
    )
    return doel
