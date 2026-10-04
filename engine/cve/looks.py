"""De 24 looks: welke er zijn, wat de gebruiker koos, en hoe een voorbeeld eruitziet.

De LUTs staan in `looks/*.cube` (33³, eigen werk) met `looks/looks.json` als
inhoudsopgave. Daar staan de sterktes van de afwerking in 0..100, want dat is
wat de schuiven in het ontwerp tonen; naar buiten gaat alles als 0..1, want zo
staat het in `edl.Afwerking`. De omrekening gebeurt hier en nergens anders.

**Waarom de keuze in `look.json` staat en niet in `edl.json`.** Rule 3 zegt dat
`edl.json` de enige waarheid is, en dat blijft zo: de renderer kijkt alleen
daarnaar. Maar een EDL zonder videoblokken is ongeldig (`EDL.valideer()`), dus
vóór de eerste montage is er geen plek om "ik wil Blockbuster op 85 %" te
bewaren. Dat is een voorkeur van de gebruiker, net als `selectie.json`, en die
hoort dus bij de voorkeuren. `montage.maak_video()` schuift hem elke keer op de
verse EDL; `zet()` werkt een bestaande `edl.json` meteen bij.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from . import media, paths
from .edl import EDL, Afwerking, Canvas, Look

# De sfeerfilters uit het ontwerp, in die volgorde. "Alles" hoort erbij: het is
# een knop in de interface, geen sfeer in `looks.json`.
SFEREN = ["Alles", "Cinematisch", "Analoge film", "Retro", "Zwart-wit", "Warm", "Koel"]

_catalogus: dict | None = None


def catalogus() -> dict:
    """`looks/looks.json`, één keer gelezen."""
    global _catalogus
    if _catalogus is None:
        pad = paths.LOOKS / "looks.json"
        if not pad.exists():
            raise FileNotFoundError(f"De lookcatalogus ontbreekt: {pad}")
        _catalogus = json.loads(pad.read_text(encoding="utf-8"))
    return _catalogus


def lijst() -> list[dict]:
    """Alle looks, met de afwerking al in 0..1."""
    return [
        {
            "id": x["id"],
            "naam": x["naam"],
            "sfeer": x.get("sfeer") or "",
            "afwerking": {k: v / 100.0 for k, v in (x.get("afwerking") or {}).items()},
        }
        for x in catalogus()["looks"]
    ]


def vind(look_id: str) -> dict | None:
    return next((x for x in lijst() if x["id"] == look_id), None)


def lut_pad(look_id: str) -> Path | None:
    """Het `.cube`-bestand van een look, of None als er niets te doen is.

    `origineel` en `geen` leveren bewust None: dan blijft `lut3d` helemaal uit
    de keten en kan hij ook niets afrondend veranderen.
    """
    if look_id in ("", "geen", "origineel"):
        return None
    ruw = next((x for x in catalogus()["looks"] if x["id"] == look_id), None)
    if ruw is None:
        return None
    pad = paths.LOOKS / ruw["lut"]
    return pad if pad.exists() else None


# -- de keuze van de gebruiker ---------------------------------------------


def _keuzepad(project: str) -> Path:
    return paths.PROJECTEN / project / "look.json"


def keuze(project: str) -> dict:
    """Wat deze gebruiker voor dit project koos. Zonder keuze: geen look."""
    try:
        d = json.loads(_keuzepad(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"id": "geen", "sterkte": 1.0, "afwerking": asdict(Afwerking())}
    return {
        "id": str(d.get("id") or "geen"),
        "sterkte": _klem(d.get("sterkte", 1.0)),
        "afwerking": _afwerking(d.get("afwerking")),
    }


def _klem(waarde, laag: float = 0.0, hoog: float = 1.0) -> float:
    try:
        return max(laag, min(hoog, float(waarde)))
    except (TypeError, ValueError):
        return laag


def _afwerking(d) -> dict:
    """Alleen velden die `edl.Afwerking` kent, allemaal geklemd op 0..1.

    Onbekende sleutels weggooien in plaats van doorlaten: `Afwerking(**d)` zou
    er anders op klappen, en een typefout in de interface mag geen montage
    kosten.
    """
    standaard = asdict(Afwerking())
    if not isinstance(d, dict):
        return standaard
    return {k: _klem(d.get(k, v)) for k, v in standaard.items()}


def zet(project: str, look_id: str, sterkte: float, afwerking) -> dict:
    """Leg de keuze vast. Een bestaande `edl.json` gaat mee.

    Zonder dat laatste zou de knop pas bij de volgende montage iets doen, en
    dat is precies het soort stille vertraging waar niemand op rekent.
    """
    if look_id not in ("geen",) and vind(look_id) is None:
        raise ValueError(f"Onbekende look: {look_id!r}")
    gekozen = {
        "id": look_id,
        "sterkte": _klem(sterkte),
        "afwerking": _afwerking(afwerking),
    }
    pad = _keuzepad(project)
    pad.parent.mkdir(parents=True, exist_ok=True)
    deel = pad.with_name(pad.name + ".deel")
    deel.write_text(json.dumps(gekozen, indent=1, ensure_ascii=False), encoding="utf-8")
    deel.replace(pad)

    edlpad = paths.PROJECTEN / project / "edl.json"
    if edlpad.exists():
        edl = EDL.lees(edlpad)
        pas_toe(edl, gekozen)
        edl.schrijf(edlpad)
    return gekozen


def pas_toe(edl: EDL, gekozen: dict) -> EDL:
    """Zet een keuze op een EDL. Hier komen look en afwerking samen."""
    edl.look = Look(id=gekozen["id"], sterkte=float(gekozen["sterkte"]))
    edl.afwerking = Afwerking(**gekozen["afwerking"])
    return edl


# -- het voorbeeldbeeld ----------------------------------------------------


def _frameindex(edl: EDL, blok) -> int:
    """Op welk framenummer dit blok in de gerenderde montage begint.

    De compositor draait achteraan, over de aan elkaar geplakte blokken, en
    rekent korrel en filmtrilling per framenummer. Een voorbeeld van shot 12
    moet dus op dát framenummer beginnen, niet op 0. Hetzelfde sommetje als
    `render.render()` gebruikt voor `totaal_frames`.
    """
    fps = edl.canvas.fps
    index = 0
    for b in edl.video:
        if b.id == blok.id:
            return index
        index += max(1, b.frames or round(b.duur * fps))
    return 0


def _bronframe(project: str, clip: str | None) -> tuple[Path, float, int]:
    """Welke proxy, welk tijdstip en welk framenummer het voorbeeld laat zien.

    Liefst een shot dat echt in de montage zit — dan ziet de gebruiker zijn
    eigen beeld in de kleur die hij kiest. Zonder EDL valt hij terug op de
    eerste proxy.
    """
    pdir = paths.PROJECTEN / project
    proxies = pdir / "proxies"
    try:
        edl = EDL.lees(pdir / "edl.json")
    except Exception:  # noqa: BLE001 — geen of kapotte EDL mag geen voorbeeld blokkeren
        edl = None

    if clip:
        pad = proxies / f"{clip}.mp4"
        if pad.exists():
            blok = next((b for b in edl.video if b.clip == clip), None) if edl else None
            if blok is not None:
                return pad, blok.bron_start, _frameindex(edl, blok)
            return pad, max(0.5, media.probe(pad).duur / 3.0), 0

    if edl is not None:
        langste = max(edl.video, key=lambda b: b.duur, default=None)
        if langste is not None:
            pad = proxies / f"{langste.clip}.mp4"
            if pad.exists():
                # Het éérste frame van het shot, niet het midden: van dát frame
                # weten we het framenummer in de montage, en daarmee de stand
                # van korrel en filmtrilling.
                return pad, langste.bron_start, _frameindex(edl, langste)

    alle = sorted(proxies.glob("*.mp4"))
    if not alle:
        raise ValueError("Dit project heeft nog geen proxies; verwerk het eerst.")
    return alle[0], max(0.5, media.probe(alle[0]).duur / 3.0), 0


def _canvas_en_seed(project: str) -> tuple[Canvas, int]:
    """Canvas en effectseed van de montage, of de standaard als die er nog niet is.

    De seed hoort erbij: korrel en filmtrilling rekenen ermee, en met een
    andere seed is het voorbeeld niet meer hetzelfde beeld als de render.
    """
    edlpad = paths.PROJECTEN / project / "edl.json"
    if edlpad.exists():
        try:
            edl = EDL.lees(edlpad)
            return edl.canvas, edl.effectseed
        except Exception:  # noqa: BLE001
            pass
    return Canvas(), 0


def voorbeeld(
    project: str,
    look_id: str,
    sterkte: float,
    afwerking,
    *,
    clip: str | None = None,
    breedte: int = 0,
) -> dict:
    """Eén frame door precies de keten van de render, als PNG.

    Daarom is het voorbeeld kleurgetrouw: de kleur komt uit dezelfde WGSL-
    shaders die de export gebruikt (`compositor.frames()`), op hetzelfde
    framenummer, met dezelfde seed. Wat verschilt is de resolutie (proxy, en
    eventueel verkleind voor een tegel) en de encoder — JPEG in plaats van
    H.264.

    **PNG en niet JPG.** Gemeten 03-10-2026: een JPG op `-q:v 2` kost ΔE2000
    gemiddeld 0,74 en maximaal 9,9 ten opzichte van wat de compositor eruit
    gaf — op een vlak kleurvlak zelfs 1,0 over het hele beeld. Voor een beeld
    dat er is om kleur te beoordelen is dat precies het verkeerde verlies. PNG
    is exact (ΔE 0,00) en een tegel van 220 px kost zo'n 100 kB.

    Ontbreekt het compositor-binary, dan valt hij terug op de ffmpeg-keten.
    Dan is het voorbeeld niet meer gelijk aan de export; `cve doctor` en het
    render-log zeggen dat.

    `breedte=0` betekent: op canvasformaat laten staan. Dat is wat de
    gouden-frames-test gebruikt — verkleinen zou de korrel veranderen.
    """
    from . import compositor
    from .render import voorbeeldfilter

    look = Look(id=look_id, sterkte=_klem(sterkte))
    afw = Afwerking(**_afwerking(afwerking))
    canvas, seed = _canvas_en_seed(project)
    bron, t, frameindex = _bronframe(project, clip)

    sleutel = json.dumps(
        {
            "look": asdict(look),
            "afwerking": asdict(afw),
            "bron": bron.name,
            "t": round(t, 3),
            "frame": frameindex,
            "canvas": asdict(canvas),
            "seed": seed,
            "breedte": int(breedte),
            # Wie de kleur rekent hoort in de sleutel: na een herbouw van de
            # compositor (of met BEATCUT_COMPOSITOR=0) is een oud voorbeeld
            # gewoon de verkeerde kleur.
            "kleurweg": compositor.sleutel(),
        },
        sort_keys=True,
    )
    naam = hashlib.sha1(sleutel.encode("utf-8")).hexdigest()[:16]
    doel = paths.project_dir(project) / "cache" / "look" / f"{naam}.png"
    if doel.exists():
        return {"pad": str(doel), "uit_cache": True, "clip": bron.stem}

    doel.parent.mkdir(parents=True, exist_ok=True)
    aanloop = min(2.0, t)
    ff = str(paths.ffmpeg())
    # Grof springen met -ss vóór -i, de rest eraf in de keten. Precies zoals
    # `render._render_blok` het doet — zie de uitleg bij `_blokfilter`.
    springen = ["-ss", f"{max(0.0, t - 2.0):.3f}"]

    if compositor.aan():
        # Kaderen doet ffmpeg, kleuren doet de compositor, verkleinen daarna.
        filters = voorbeeldfilter(look, afw, canvas, aanloop=aanloop, breedte=0,
                                  seed=seed, uitvoer="rgba")
        decode = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", *springen, "-i", str(bron),
             "-frames:v", "1", "-map", "0:v:0", "-an", "-vf", filters,
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            capture_output=True, timeout=300,
        )
        verwacht = canvas.breedte * canvas.hoogte * 4
        if decode.returncode != 0 or len(decode.stdout) != verwacht:
            laatste = (decode.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
            raise media.MediaFout(
                f"Voorbeeldframe van look {look_id} lezen faalde: {' | '.join(laatste)}"
            )
        rgba = compositor.frames(decode.stdout, canvas.breedte, canvas.hoogte,
                                 look, afw, seed=seed, vanaf=frameindex)
        naschaal = ["-vf", f"scale={breedte}:-2:flags=bicubic"] if breedte > 0 else []
        r = subprocess.run(
            [ff, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgba",
             "-s", f"{canvas.breedte}x{canvas.hoogte}", "-i", "-",
             "-frames:v", "1", *naschaal, str(doel)],
            input=rgba, capture_output=True, timeout=300,
        )
        stderr = (r.stderr or b"").decode("utf-8", "replace")
    else:
        filters = voorbeeldfilter(look, afw, canvas, aanloop=aanloop,
                                  breedte=breedte, seed=seed)
        r = subprocess.run(
            [ff, "-y", "-hide_banner", "-loglevel", "error", *springen,
             "-i", str(bron), "-frames:v", "1", "-map", "0:v:0", "-an",
             "-vf", filters, str(doel)],
            capture_output=True, text=True, timeout=300,
        )
        stderr = r.stderr or ""

    if r.returncode != 0 or not doel.exists():
        laatste = stderr.strip().splitlines()[-3:]
        raise media.MediaFout(f"Voorbeeld van look {look_id} faalde: {' | '.join(laatste)}")
    return {"pad": str(doel), "uit_cache": False, "clip": bron.stem}
