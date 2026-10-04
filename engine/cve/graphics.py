"""Fase 5 - motion graphics.

Overlays worden niet als losse HTML per video geschreven, maar als een klein
aantal **sjablonen** die met variabelen gevuld worden. Dat scheelt tokens
(het model vult een titel in plaats van 200 regels HTML te schrijven) en het
maakt de huisstijl afdwingbaar: alle kleuren en fonts komen uit
`brands/<merk>/brand.json`.

    sjabloon + variabelen  ->  hyperframes render --format mov  ->  ProRes 4444
    (transparant)          ->  ffmpeg overlay over de montage

De sjablonen staan in `brands/sjablonen/` en zijn merk-onafhankelijk; het merk
levert alleen de waarden.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .edl import EDL, OverlayBlok

SJABLONEN = {
    "titel": "sjablonen/titel.html",
    "lowerthird": "sjablonen/titel.html",  # zelfde kaart, andere positie
    "titel20": "sjablonen/titel20.html",   # de twintig titelstijlen
    "eindkaart": "sjablonen/eindkaart.html",
    "ondertitels": "sjablonen/ondertitels.html",
}


class GraphicsFout(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Merk
# --------------------------------------------------------------------------


@dataclass
class Merk:
    id: str
    naam: str
    kleuren: dict
    typografie: dict
    watermerken: list
    veilige_marges: dict

    @property
    def primair(self) -> str:
        return self.kleuren.get("primair", "#2dd4bf")

    @property
    def tekst(self) -> str:
        return self.kleuren.get("tekst", "#ffffff")


def laad_merk(naam: str) -> Merk:
    pad = paths.BRANDS / naam / "brand.json"
    if not pad.exists():
        pad = paths.BRANDS / "prive" / "brand.json"
    d = json.loads(pad.read_text(encoding="utf-8")) if pad.exists() else {}
    return Merk(
        id=d.get("id", naam),
        naam=d.get("naam", naam),
        kleuren=d.get("kleuren", {}),
        typografie=d.get("typografie", {}),
        watermerken=d.get("watermerken", []),
        veilige_marges=d.get("veilige_marges", {}),
    )


# --------------------------------------------------------------------------
# Renderen
# --------------------------------------------------------------------------


#: Wat de gebruiker te zien krijgt als de titels niet getekend kunnen worden.
#: `render.py` geeft deze tekst als waarschuwing terug en de app toont hem;
#: stil overslaan levert een export zonder titels op terwijl de voorvertoning
#: ze wél laat zien, en dat is de ene belofte die niet mag breken.
ONDERDELEN_ONTBREKEN = (
    "De titelmotor staat nog niet klaar. BeatCut haalt die eenmalig op "
    "(ongeveer 400 MB); daarna werkt het offline."
)


def _hyperframes() -> list[str]:
    """Het commando om HyperFrames te draaien.

    Zoekt via `paths`: de steunmap (wat `onderdelen.py` ophaalt), de projectmap
    en als laatste `PATH`.

    **Geen terugval op `npx hyperframes` meer.** Die haalde midden in een
    render een niet-vastgezette versie van het internet — dat breekt regel 5
    (een render heeft nooit internet nodig) én het maakte `onderdelen.status()`
    een leugenaar: die meldde "ontbreekt" terwijl de render het soms toch
    deed, met een andere versie dan waarop getoetst is.
    """
    gevonden = paths.hyperframes()
    if gevonden:
        return gevonden
    raise GraphicsFout(ONDERDELEN_ONTBREKEN)


def _omgeving() -> dict:
    """De omgeving voor HyperFrames: eigen Node op PATH, eigen browser erbij.

    **De browser moet hard aangewezen worden.** HyperFrames zoekt er anders
    zelf een: eerst zijn cache in `~/.cache`, dan een Chrome van het systeem,
    en pas daarna haalt hij er een op — midden in een render, zonder dat
    iemand dat verwacht. `HYPERFRAMES_BROWSER_PATH` is het enige pad dat vóór
    al die caches gaat (`ensureBrowser` in zijn eigen code), dus daarmee
    tekent de export op precies de build die wij neergezet hebben.
    """
    import os

    from . import onderdelen

    omgeving = dict(os.environ)
    node = paths.node_bin()
    if node is not None:
        omgeving["PATH"] = str(node.parent) + os.pathsep + omgeving.get("PATH", "")
    chrome = onderdelen.chrome_pad()
    if chrome is not None:
        omgeving["HYPERFRAMES_BROWSER_PATH"] = str(chrome)
    return omgeving


def _variabelen(blok: OverlayBlok, merk: Merk) -> dict:
    inhoud = dict(blok.inhoud or {})
    basis = {
        "kleur": inhoud.pop("kleur", merk.primair),
        "tekstkleur": inhoud.pop("tekstkleur", merk.tekst),
        "duur": round(blok.duur, 3),
    }
    if blok.soort == "lowerthird":
        basis.setdefault("positie", "linksonder")
    return {**basis, **inhoud}


HYPERFRAMES_JSON = {
    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
    "paths": {"blocks": ".", "components": "onderdelen", "assets": "."},
    "media": {"autoProxy": False},
}


def _op_maat(sjabloon: Path, breedte: int, hoogte: int, duur: float, doel: Path) -> Path:
    """Schrijf een kopie van het sjabloon op de juiste maat en lengte.

    Twee dingen die HyperFrames uit de HTML leest voordat het script van de
    compositie draait, en die dus hier gezet moeten worden:

    - **Afmeting.** `--resolution` werkt niet samen met transparante uitvoer;
      de alpha-route past de deviceScaleFactor niet toe.
    - **Duur.** `data-duration` in de HTML is leidend. Een `duur`-variabele die
      het script later zet komt te laat: de renderer heeft dan al bepaald
      hoeveel frames hij maakt. Dat leverde een ondertitelspoor van tien
      seconden op onder een montage van tachtig.
    """
    tekst = sjabloon.read_text(encoding="utf-8")
    tekst = tekst.replace('width=1920, height=1080', f"width={breedte}, height={hoogte}")
    tekst = tekst.replace("width:1920px;height:1080px", f"width:{breedte}px;height:{hoogte}px")
    tekst = tekst.replace('data-width="1920"', f'data-width="{breedte}"')
    tekst = tekst.replace('data-height="1080"', f'data-height="{hoogte}"')
    tekst = re.sub(r'data-duration="[\d.]+"', f'data-duration="{duur:.3f}"', tekst)
    # De veilige marges in het sjabloon rekenen met 1920x1080; maak ze relatief.
    tekst = tekst.replace("1920*0.055", f"{breedte}*0.055").replace("1080*0.08", f"{hoogte}*0.08")
    tekst = tekst.replace("H * 0.115", f"{hoogte} * 0.115").replace("H * 0.10", f"{hoogte} * 0.10")
    doel.parent.mkdir(parents=True, exist_ok=True)
    doel.write_text(tekst, encoding="utf-8")
    return doel


def _hulpbestanden(sjabloonmap: Path, werk: Path) -> None:
    """Alles wat de sjablonen náást de HTML nodig hebben, mee naar de werkmap.

    De composities verwijzen naar `titelstijlen.css`, `titel20.js`, de
    meegeleverde lettertypes en de lokale GSAP. Zonder deze kopie rendert een
    titel zonder vormgeving, zonder animatie of in een vervangend lettertype.

    **De lettertypes en GSAP staan er lokaal omdat een render nooit het
    internet nodig mag hebben** (CLAUDE.md regel 5). Kopiëren gebeurt één keer
    per project: de werkmap blijft tussen renders staan.
    """
    for patroon in ("*.css", "*.js"):
        for hulp in sjabloonmap.glob(patroon):
            shutil.copy2(hulp, werk / hulp.name)
    for naam, bron in (("vendor", sjabloonmap / "vendor"), ("fonts", paths.BRANDS / "fonts")):
        doel = werk / naam
        if bron.is_dir() and not doel.exists():
            shutil.copytree(bron, doel)


def render_overlay(
    blok: OverlayBlok,
    merk: Merk,
    doelmap: Path,
    *,
    breedte: int = 1920,
    hoogte: int = 1080,
    fps: int = 30,
    log=print,
) -> Path:
    """Render een overlay naar een transparante ProRes 4444-MOV."""
    naam = SJABLONEN.get(blok.soort)
    if not naam:
        raise GraphicsFout(f"Geen sjabloon voor overlay-soort '{blok.soort}'.")
    sjabloon = paths.BRANDS / naam
    if not sjabloon.exists():
        raise GraphicsFout(f"Sjabloon ontbreekt: {sjabloon}")

    doelmap.mkdir(parents=True, exist_ok=True)
    doel = doelmap / f"{blok.id}.mov"
    if doel.exists() and doel.stat().st_size > 0:
        return doel

    # Werkmap met een eigen hyperframes.json, zodat de compositie los van de
    # merkmap gerenderd wordt en de sjablonen ongewijzigd blijven.
    werk = doelmap / "_werk"
    werk.mkdir(parents=True, exist_ok=True)
    (werk / "hyperframes.json").write_text(json.dumps(HYPERFRAMES_JSON, indent=2), encoding="utf-8")
    _hulpbestanden(sjabloon.parent, werk)
    compositie = _op_maat(sjabloon, breedte, hoogte, blok.duur, werk / f"{blok.id}.html")

    cmd = [
        *_hyperframes(),
        "render",
        str(werk),
        "-c",
        compositie.name,
        "--format",
        "mov",
        "--fps",
        str(fps),
        "--quiet",
        "--variables",
        json.dumps(_variabelen(blok, merk), ensure_ascii=False),
        "-o",
        str(doel),
    ]

    omgeving = {**_omgeving(), "HYPERFRAMES_TELEMETRY": "0"}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=omgeving)
    if r.returncode != 0 or not doel.exists():
        laatste = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
        raise GraphicsFout(f"Overlay {blok.id} faalde: " + " | ".join(laatste))
    log(f"  overlay {blok.id} ({blok.soort}) klaar")
    return doel


def render_alle(
    edl: EDL, projectmap: Path, *, log=print, waarschuwingen: list[str] | None = None
) -> dict[str, Path]:
    """Render elke overlay in de EDL. Geeft {blok-id: bestandspad}.

    `waarschuwingen` is een lijst waar elke overgeslagen titel een regel in
    achterlaat. Die reist mee naar de app: een export zonder titels mag nooit
    alleen in een logbestand staan dat niemand opent.
    """
    if not edl.overlay:
        return {}
    merk = laad_merk(edl.merk)
    doelmap = projectmap / "composities"
    log(f"Motion graphics: {len(edl.overlay)} overlay(s), merk '{merk.naam}'")

    uit: dict[str, Path] = {}
    gemist: list[str] = []
    for blok in edl.overlay:
        try:
            uit[blok.id] = render_overlay(
                blok,
                merk,
                doelmap,
                breedte=edl.canvas.breedte,
                hoogte=edl.canvas.hoogte,
                fps=edl.canvas.fps,
                log=log,
            )
        except GraphicsFout as e:
            log(f"  overgeslagen: {e}")
            gemist.append(str(e))
    if gemist and waarschuwingen is not None:
        # Eén regel voor de gebruiker, niet één per titel: twintig keer
        # dezelfde reden is geen twintig problemen.
        reden = gemist[0] if len(set(gemist)) == 1 else " ".join(dict.fromkeys(gemist))
        waarschuwingen.append(
            f"{len(gemist)} van de {len(edl.overlay)} titel(s) staan niet in de "
            f"video. {reden}"
        )
    return uit


# --------------------------------------------------------------------------
# Standaard-overlays
# --------------------------------------------------------------------------


def ondertitel_overlay(regels: list[dict], edl: EDL) -> OverlayBlok:
    """Alle ondertitels in één compositie.

    Bewust niet een overlay per regel: dan zou je honderden renders krijgen.
    Eén compositie over de volle lengte met per regel een eigen `data-start`
    is even nauwkeurig en rendert in één keer.
    """
    return OverlayBlok(
        id="o-ondertitels",
        soort="ondertitels",
        tijdlijn_start=0.0,
        duur=round(edl.duur, 3),
        inhoud={"regels": json.dumps(regels, ensure_ascii=False)},
    )


def standaard_overlays(
    edl: EDL,
    *,
    titel: str = "",
    eyebrow: str = "",
    onder: str = "",
    slot: str = "",
) -> list[OverlayBlok]:
    """Een openingstitel en een eindkaart, netjes op de montage gelegd.

    De titel begint pas na het eerste shot zijn instap, en de eindkaart valt
    samen met de laatste seconden zodat de muziek en het beeld samen uitfaden.
    """
    uit: list[OverlayBlok] = []
    if not edl.video:
        return uit

    if titel:
        eerste = edl.video[0]
        duur = min(4.0, max(2.0, eerste.duur))
        uit.append(
            OverlayBlok(
                id="o-titel",
                soort="titel",
                tijdlijn_start=round(min(0.6, eerste.duur * 0.2), 3),
                duur=round(duur, 3),
                inhoud={
                    "titel": titel,
                    "eyebrow": eyebrow,
                    "onder": onder,
                    "positie": "linksonder",
                },
            )
        )

    if slot:
        duur = 3.5
        start = max(0.0, edl.duur - duur)
        uit.append(
            OverlayBlok(
                id="o-slot",
                soort="eindkaart",
                tijdlijn_start=round(start, 3),
                duur=duur,
                inhoud={"titel": slot},
            )
        )
    return uit
