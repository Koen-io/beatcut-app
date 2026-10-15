"""Een voorbeeldclip per montagestijl, gemaakt met de eigen motor.

In stap 2 stonden alleen namen: velocity, hype, glitch. Dat zegt niemand iets.
GoPro Quik laat per stijl een tegeltje zien dat bij het aanwijzen een paar
seconden speelt, en dan is in één oogopslag duidelijk wat "elke tel snijden"
betekent tegenover "per frase".

**Hij rendert door dezelfde motor als een echte video.** Een nagemaakt
voorbeeld zou precies de belofte breken die de tegel doet: dit is wat je
krijgt. Dus ingest, analyse, regie met díe montagestijl, en de render door de
compositor — alleen op 320 px en zonder geluid.

**Het bronmateriaal maakt ffmpeg zelf** (`BRONNEN` hieronder). Dat is geen
nood maar een keuze: beelden van een gebruiker horen niet in een installer, en
materiaal van buiten brengt een licentie mee die niemand kan nazoeken. Veertien
synthetische clips, elk met een eigen kleur en beweging, laten het snijritme
juist scherp zien: bij elke snede verandert het beeld volledig.

**De tel komt uit een kliktrack**, ook door ffmpeg gemaakt. Zonder muziek valt
de regisseur terug op `min_shot` en is er geen tel om op te snijden — en dan
toont een tegel voor Velocity precies hetzelfde ritme als een voor Ambient.
De klik gaat niet mee in het eindbestand; de tegels zijn stil.

Draaien:

    .venv/bin/cve stijlvoorbeelden            # alle veertien
    .venv/bin/cve stijlvoorbeelden --stijl hype --opnieuw

De uitkomst gaat naar `app/public/stijlvoorbeelden/` en daarmee de app-bundel
in: geen download, dus ze werken offline. `tests/test_stijlvoorbeelden.py`
faalt zodra er een stijl zonder voorbeeld is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import montagestijl, paths

# Waar de tegels terechtkomen. Onder `app/public/` omdat Vite die map
# ongewijzigd in `dist/` zet, en Tauri `dist/` in de bundel — zo gaan ze mee
# zonder dat er iets te downloaden valt.
UITVOER = "app/public/stijlvoorbeelden"

# Hoe lang een tegel speelt. Koens kader is 3-5 s: lang genoeg om een ritme te
# horen zien, kort genoeg om onder de muis nog een tegel te zijn.
DUUR = 4.5
BREEDTE = 320
# Het tempo van de kliktrack. 120 geeft een hele tel per halve seconde: op
# Velocity (elke tel) zijn dat negen snedes in een tegel, op Ambient één shot.
BPM = 120
# Zoveel bronclips. Meer dan het aantal snedes van de snelste stijl, anders
# komt dezelfde clip twee keer achter elkaar en lijkt er niet gesneden.
AANTAL_BRONNEN = 14
BRONDUUR = 6.0


@dataclass(frozen=True)
class Bron:
    """Eén synthetische bronclip: waar het beeld vandaan komt en hoe het eruitziet.

    `bron` is een lavfi-bron, `kleur` een filterketen erachter. De ketens
    gebruiken alleen filters die de meegeleverde LGPL-ffmpeg heeft — `eq` zit
    er bijvoorbeeld niet in (GPL), dus kleurbewerking gaat via `curves`,
    `hue` en `colorbalance`.
    """

    naam: str
    bron: str
    kleur: str


def _tint(rood: float, groen: float, blauw: float) -> str:
    """Grijs beeld naar één kleur: een duotone.

    `colorchannelmixer` rekent R_uit = rr*R + rg*G + rb*B. Op een grijs beeld
    is R = G = B = L, dus een hele rij op `kleur/3` levert R_uit = kleur * L.
    Donker blijft donker, licht krijgt de kleur — precies wat een duotone doet,
    en de marmerstructuur van de fractal blijft staan.

    De weg via de eigen LUT's uit `looks/` is geprobeerd en afgevallen
    (04-10-2026): die zijn gemaakt voor camerabeelden. Op het regenboogbeeld
    dat de fractal zelf uitrekent geven ze schreeuwerige vlakken, en op een
    grijs beeld raken ze het nauwelijks aan — veertien clips zagen er dan
    alsnog hetzelfde uit.
    """
    r, g, b = rood / 3, groen / 3, blauw / 3
    return (
        f"colorchannelmixer=rr={r:.3f}:rg={r:.3f}:rb={r:.3f}"
        f":gr={g:.3f}:gg={g:.3f}:gb={g:.3f}"
        f":br={b:.3f}:bg={b:.3f}:bb={b:.3f}"
    )


def _bronnen() -> list[Bron]:
    """Veertien clips die onderling zo veel verschillen dat elke snede opvalt.

    Dat is het hele doel: wie de tegel van Velocity naast die van Ambient legt
    moet het verschil in snijritme zíen, en dat kan alleen als een snede een
    zichtbare gebeurtenis is.

    **Allemaal inzoomende fractals, elk in een eigen kleur.** Drie andere
    bronnen zijn geprobeerd en afgevallen (04-10-2026):

    - `life` (cellulaire automaat) is per pixel chaos. De analyse vindt dat
      prachtig — maximale "beweging" — dus de regisseur koos niets anders meer
      en veertien tegels bestonden uit beeldruis.
    - `gradients` is het omgekeerde: zo vlak dat de analyse er geen bruikbaar
      segment in vindt.
    - `testsrc2` ziet eruit als een testbeeld, en dat is precies niet wat een
      tegel moet uitstralen.

    Een fractalzoom heeft wél wat de analyse zoekt — detail, scherpte, een
    camera die beweegt — en ziet er met een duotone overheen uit als marmer of
    wolken in plaats van als wiskunde.
    """
    # (naam, x, y, van, tot, binnenkant, kleur)
    recepten = [
        ("ijsblauw", -0.743644, 0.131826, 0.012, 0.0035, "mincol", (0.55, 0.80, 1.15)),
        ("amber", -1.256600, 0.380000, 0.020, 0.0045, "convergence", (1.25, 0.82, 0.38)),
        ("mos", 0.292986, 0.611785, 0.015, 0.0030, "period", (0.55, 1.10, 0.62)),
        ("magenta", -0.159200, -1.031700, 0.010, 0.0025, "mincol", (1.20, 0.52, 1.00)),
        ("staal", -0.745300, 0.112700, 0.008, 0.0020, "convergence", (0.80, 0.90, 1.00)),
        ("zand", -0.235125, 0.827215, 0.014, 0.0032, "mincol", (1.15, 1.00, 0.68)),
        ("diepzee", -0.775684, 0.136467, 0.009, 0.0022, "period", (0.32, 0.70, 1.00)),
        ("koper", 0.324505, 0.048551, 0.016, 0.0036, "mincol", (1.30, 0.70, 0.42)),
        ("mist", -0.101096, 0.956287, 0.011, 0.0026, "convergence", (0.92, 0.96, 1.05)),
        ("violet", -0.550330, 0.625935, 0.013, 0.0028, "period", (0.80, 0.55, 1.20)),
        ("olijf", -0.812300, 0.201500, 0.018, 0.0040, "mincol", (0.90, 1.00, 0.52)),
        ("rook", -0.722000, 0.246000, 0.010, 0.0024, "convergence", (0.85, 0.82, 0.88)),
        ("kers", 0.001643, -0.822467, 0.012, 0.0030, "mincol", (1.30, 0.48, 0.52)),
        ("jade", -0.748000, 0.100000, 0.015, 0.0034, "period", (0.45, 1.05, 0.95)),
    ]
    uit = []
    for naam, x, y, van, tot, binnen, kleur in recepten[:AANTAL_BRONNEN]:
        bron = (
            f"mandelbrot=s=640x360:rate=30:start_x={x}:start_y={y}"
            f":start_scale={van}:end_scale={tot}:maxiter=320"
            f":inner={binnen}:outer=normalized_iteration_count"
        )
        # Korrel moet erbij: zonder ziet de analyse een te glad beeld en vindt
        # hij geen bruikbaar segment — en dan is er niets om te monteren.
        bewerking = (
            f"scale=1280:720:flags=bicubic,hue=s=0,{_tint(*kleur)},"
            f"curves=all='0/0.03 0.5/0.48 1/0.97',gblur=sigma=0.5,"
            f"noise=alls=6:allf=t,vignette=PI/5,format=yuv420p"
        )
        uit.append(Bron(naam=naam, bron=bron, kleur=bewerking))
    return uit


def _ffmpeg(*args: str, wat: str) -> None:
    uit = subprocess.run(
        [str(paths.ffmpeg()), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if uit.returncode != 0:
        raise RuntimeError(f"{wat} mislukte:\n{uit.stderr.strip()[:800]}")


def maak_bronclip(bron: Bron, doel: Path) -> None:
    """Eén synthetische clip van `BRONDUUR` seconden."""
    doel.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-f", "lavfi", "-i", bron.bron,
        "-t", str(BRONDUUR),
        "-vf", bron.kleur,
        # mpeg4 zit in elke ffmpeg-build, ook de LGPL-variant die meegaat.
        # Dit is bronmateriaal voor de ingest; die maakt er zelf een h264-proxy
        # van, dus de codec hier hoeft alleen leesbaar te zijn.
        "-c:v", "mpeg4", "-q:v", "3", "-r", "30",
        str(doel),
        wat=f"bronclip {bron.naam}",
    )


def maak_kliktrack(doel: Path, *, bpm: int = BPM, seconden: float = 40.0) -> None:
    """Een klik op elke tel. Hieraan hangt de regisseur zijn snijpunten op.

    Een korte piep per tel is genoeg: de muziekanalyse zoekt onsets, en dit
    zijn er veertien per minuut meer dan genoeg. De track gaat niet mee in de
    tegels — die zijn stil (`-an` in `_verklein`).
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    tel = 60.0 / bpm
    # Een sinus die alleen rond het begin van elke tel klinkt. `mod(t,tel)`
    # geeft de plek binnen de tel; onder 25 ms is het een tik.
    _ffmpeg(
        "-f", "lavfi",
        "-i", f"sine=frequency=1760:duration={seconden}:sample_rate=48000",
        "-af", f"volume='if(lt(mod(t,{tel}),0.025),0.9,0)':eval=frame",
        "-c:a", "pcm_s16le",
        str(doel),
        wat="kliktrack",
    )


def _verklein(bron: Path, doel: Path, *, breedte: int = BREEDTE) -> None:
    """De render terugbrengen tot een tegel: klein, stil, en snel te starten.

    `faststart` zet de index vooraan, anders moet de speler het hele bestand
    binnenhebben voordat er iets beweegt — op een tegel die onder de muis moet
    aanspringen is dat het verschil tussen werkt en werkt niet.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    encoder, opties = _tegel_encoder()
    _ffmpeg(
        "-i", str(bron),
        # Afkappen op `DUUR`. De regisseur legt elke snede op een hele tel, dus
        # de montage komt uit op een veelvoud daarvan: een stijl die per twee
        # maten snijdt levert 8 s waar er 4,5 gevraagd is. Een tegel moet
        # overal even lang zijn — hij speelt toch in herhaling, dus waar hij
        # rondgaat is willekeurig.
        "-t", f"{DUUR}",
        "-an",
        "-vf", f"scale={breedte}:-2:flags=bicubic",
        "-c:v", encoder, *opties,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(doel),
        wat=f"tegel {doel.name}",
    )


def _tegel_encoder() -> tuple[str, list[str]]:
    """Welke encoder de tegels maakt.

    Hetzelfde probleem als in `media.video_encoder()`: de meegeleverde ffmpeg
    is LGPL en heeft dus geen x264. VideoToolbox op de Mac, anders wat er is.
    """
    from . import media

    naam, _ = media.video_encoder()
    if naam == "libopenh264":
        return naam, ["-b:v", "500k"]
    if "videotoolbox" in naam:
        return naam, ["-b:v", "500k", "-realtime", "0"]
    return naam, ["-b:v", "500k"]


def _poster(video: Path, doel: Path) -> None:
    """Een stilstaand beeld voor de tegel die nog niet speelt.

    Niet frame 0: een montage begint vaak op zwart of midden in een overgang.
    Een vijfde erin staat altijd in het eerste shot.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-ss", f"{DUUR / 5:.2f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "4",
        str(doel),
        wat=f"poster {doel.name}",
    )


def doelmap() -> Path:
    return paths.ROOT / UITVOER


def ontbreekt(map_: Path | None = None) -> list[str]:
    """Welke montagestijlen nog geen voorbeeld hebben. Leeg is goed."""
    m = map_ or doelmap()
    return [
        s for s in montagestijl.ORDE
        if not (m / f"{s}.mp4").exists() or not (m / f"{s}.jpg").exists()
    ]


def maak(
    *,
    alleen: str = "",
    opnieuw: bool = False,
    log=print,
) -> list[Path]:
    """Render een voorbeeld voor elke montagestijl. Geeft de gemaakte bestanden terug.

    Het bronmateriaal en de analyse worden één keer gemaakt en daarna door alle
    veertien stijlen gedeeld: alleen de regie en de render verschillen, en dat
    is precies het verschil dat de tegels moeten tonen.
    """
    from .analyse import analyseer
    from .director import Brief, kies_regisseur
    from .ingest import ingest as _ingest
    from .render import RenderOpties
    from .render import render as _render

    stijlen = [alleen] if alleen else list(montagestijl.ORDE)
    onbekend = [s for s in stijlen if s not in montagestijl.ORDE]
    if onbekend:
        raise ValueError(f"onbekende montagestijl(en): {', '.join(onbekend)}")

    uit = doelmap()
    uit.mkdir(parents=True, exist_ok=True)

    # In een eigen map, niet tussen de projecten van de gebruiker: die lijst
    # staat in stap 1 en daar hoort geen gereedschap in. `paths.PROJECTEN` is
    # een constante die bij het importeren gezet wordt, dus hier omzetten —
    # de omgevingsvariabele komt te laat.
    werkmap = Path(tempfile.gettempdir()) / "beatcut-stijlvoorbeelden"
    oude = paths.PROJECTEN
    paths.PROJECTEN = werkmap
    try:
        project = "bron"
        pdir = werkmap / project
        if opnieuw and pdir.exists():
            shutil.rmtree(pdir)

        bronnen = _bronnen()
        bronmap = pdir / "bronnen"
        bronmap.mkdir(parents=True, exist_ok=True)
        for i, b in enumerate(bronnen, start=1):
            doel = bronmap / f"{i:02d}-{b.naam}.mp4"
            if doel.exists() and doel.stat().st_size > 0:
                continue
            log(f"  bronclip {i}/{len(bronnen)}  {b.naam}")
            maak_bronclip(b, doel)

        klik = pdir / "muziek" / "klik.wav"
        if not klik.exists():
            log(f"  kliktrack {BPM} BPM")
            maak_kliktrack(klik)

        if not (pdir / "ingest.json").exists():
            log("  ingest")
            _ingest(project, log=lambda *_: None)
        if not (pdir / "analysis.json").exists():
            log("  analyse")
            analyseer(project, stijl="actie", log=lambda *_: None)

        analyse = json.loads((pdir / "analysis.json").read_text(encoding="utf-8"))
        gemaakt: list[Path] = []
        for n, stijl in enumerate(stijlen, start=1):
            log(f"[{n}/{len(stijlen)}] {stijl}")
            voorstel = kies_regisseur("preset").stel_voor(
                analyse, Brief(doelduur=DUUR, stijl="actie", montage=stijl, vorm="16:9")
            )
            voorstel.edl.schrijf(pdir / "edl.json")
            bestand = _render(project, opties=RenderOpties(modus="preview"))
            _verklein(Path(bestand), uit / f"{stijl}.mp4")
            _poster(uit / f"{stijl}.mp4", uit / f"{stijl}.jpg")
            gemaakt += [uit / f"{stijl}.mp4", uit / f"{stijl}.jpg"]
            kb = (uit / f"{stijl}.mp4").stat().st_size / 1024
            log(f"        {len(voorstel.edl.video)} shots · {kb:.0f} KB")

        _schrijf_index(uit)
        return gemaakt
    finally:
        paths.PROJECTEN = oude


def _schrijf_index(uit: Path) -> None:
    """Een klein overzicht naast de tegels: wat er ligt en waar het van komt.

    De app leest het niet — die kent de stijl-id's al. Het staat er voor wie
    de map openslaat en wil weten of dit materiaal van iemand is.
    """
    (uit / "LEESMIJ.md").write_text(
        "# Voorbeeldtegels per montagestijl\n\n"
        "Gemaakt door `cve stijlvoorbeelden`. Niet met de hand bewerken: een\n"
        "wijziging in `styles/montage/` hoort hier doorheen te lopen.\n\n"
        "Het bronmateriaal is door ffmpeg zelf gegenereerd (fractals, cellulaire\n"
        "automaten en kleurverlopen) en de tel komt uit een gegenereerde\n"
        "kliktrack. Er zit dus geen materiaal van derden in en geen beeld van\n"
        "een gebruiker — zie `engine/cve/stijlvoorbeelden.py`.\n\n"
        f"Elke tegel is {DUUR:.1f} s, {BREEDTE} px breed, zonder geluid.\n\n"
        + "".join(f"- `{s}.mp4` + `{s}.jpg`\n" for s in montagestijl.ORDE),
        encoding="utf-8",
    )


def gegevens() -> dict:
    """Wat er ligt, voor `cve doctor` en de tests."""
    m = doelmap()
    return {
        "map": str(m),
        "ontbreekt": ontbreekt(m),
        "bytes": sum(q.stat().st_size for q in m.glob("*") if q.is_file()) if m.exists() else 0,
    }


__all__ = ["maak", "ontbreekt", "doelmap", "gegevens", "DUUR", "BREEDTE", "BPM"]


def _hoofd() -> None:  # pragma: no cover - alleen voor handmatig draaien
    print(json.dumps(gegevens(), indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    _hoofd()
