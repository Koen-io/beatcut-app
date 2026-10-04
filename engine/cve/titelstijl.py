"""De twintig titelstijlen: welke er zijn, hoe ze eruitzien, en hoe ze in de
montage komen.

`styles/titels/titels.json` is de enige bron. De engine leest hem hier, de
compositie (`brands/sjablonen/titel20.html`) krijgt de gekozen regel mee als
variabele `spec`, en de interface krijgt dezelfde lijst via `project.stijlen`.
Zo kan de kaart in de app nooit iets anders tonen dan wat er gerenderd wordt.

**De titelstijl zit niet in de brief.** `montage.brief_van()` bepaalt of de
montage opnieuw bedacht moet worden; een andere titelstijl verandert de snedes
niet, alleen wat er over het beeld ligt. Hij staat daarom per overlayblok in
`edl.json` — dat is ook de plek waar de renderer hem leest.

Het voorbeeldbeeld in de interface is **niet** een nagemaakte kaart maar een
echt frame uit dezelfde compositie, halverwege de animatie. Een voorbeeld dat
niet is wat er uit de render komt is erger dan geen voorbeeld (PLAN-v2.md §4.4).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

from . import paths
from .edl import EDL, OverlayBlok

# Zo groot als de kaart in het ontwerp (ontwerp/beatcut2/Main.dc.html).
VOORBEELD_B, VOORBEELD_H = 320, 180

# Waarop het voorbeeld gerenderd wordt. Groter dan de kaart, zodat het beeld
# scherp blijft op een scherm met dubbele pixeldichtheid.
RENDER_B, RENDER_H = 640, 360

# De tekst in het voorbeeld. Hetzelfde materiaal als het ontwerp gebruikt,
# zodat elke stijl met dezelfde woorden vergeleken wordt.
VOORBEELDTEKST = {
    "titel": "Garmisch-Partenkirchen",
    "eyebrow": "14 augustus",
    "onder": "700 m",
    "datum": "14 08 '26",
    "coords": "47,49° N · 11,10° O",
    "nummer": 1,
}


def _coords(lat, lon) -> str:
    """"47,49° N · 11,10° O" — zoals een kaart het schrijft, met komma's."""
    if lat is None or lon is None:
        return ""
    def graad(w: float, pos: str, neg: str) -> str:
        return f"{abs(w):.2f}".replace(".", ",") + "° " + (pos if w >= 0 else neg)
    return f"{graad(float(lat), 'N', 'Z')} · {graad(float(lon), 'O', 'W')}"

_catalogus: dict | None = None


class TitelFout(RuntimeError):
    pass


def catalogus() -> dict:
    """`styles/titels/titels.json`, één keer gelezen."""
    global _catalogus
    if _catalogus is None:
        pad = paths.STYLES / "titels" / "titels.json"
        if not pad.exists():
            raise FileNotFoundError(f"De titelcatalogus ontbreekt: {pad}")
        _catalogus = json.loads(pad.read_text(encoding="utf-8"))
    return _catalogus


def specs() -> list[dict]:
    """Alle twintig stijlen met hun volledige vormgeving."""
    return list(catalogus()["titels"])


def vind(stijl_id: str) -> dict | None:
    return next((x for x in specs() if x["id"] == stijl_id), None)


def standaard() -> str:
    return specs()[0]["id"]


def eis(stijl_id: str) -> dict:
    spec = vind(stijl_id)
    if spec is None:
        raise ValueError(
            f"Titelstijl {stijl_id!r} bestaat niet. Kies uit: "
            + ", ".join(x["id"] for x in specs())
        )
    return spec


def lijst(project: str | None = None) -> list[dict]:
    """Wat de interface nodig heeft: naam, wat de animatie doet, en het beeld.

    `voorbeeld` is `None` zolang het beeld nog niet gemaakt is; de kaart valt
    dan terug op naam en omschrijving. Het beeld maken kost een render per
    stijl, dus dat gebeurt op verzoek (`titel.voorbeelden`) en niet hier.
    """
    uit = []
    for x in specs():
        beeld = _in_project(project, x["id"]) if project else _gedeeld(x["id"])
        uit.append({
            "id": x["id"],
            "naam": x["naam"],
            "animatie": x["animatie"],
            "voorbeeld": str(beeld) if beeld.exists() else None,
        })
    return uit


def gekozen(project: str) -> str:
    """Welke titelstijl er in `edl.json` staat, of de standaard."""
    edlpad = paths.project_dir(project) / "edl.json"
    if not edlpad.exists():
        return standaard()
    try:
        edl = EDL.lees(edlpad)
    except (OSError, ValueError, KeyError, TypeError):
        return standaard()
    for o in edl.overlay:
        if o.soort == "titel20":
            keuze = (o.inhoud or {}).get("titelstijl")
            if keuze and vind(str(keuze)):
                return str(keuze)
    return standaard()


# -- de titels op de montage leggen ---------------------------------------


def _clips(project: str) -> dict[str, dict]:
    pad = paths.PROJECTEN / project / "ingest.json"
    try:
        return {c["id"]: c for c in json.loads(pad.read_text(encoding="utf-8"))["clips"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _stempel(iso: str) -> str:
    """"2026-08-14T..." wordt "14 08 '26" — zoals een camcorder het zet."""
    if len(iso) < 10:
        return ""
    jaar, maand, dag = iso[:4], iso[5:7], iso[8:10]
    return f"{dag} {maand} '{jaar[2:]}"


def zet_op(edl: EDL, project: str, stijl_id: str, *, met_internet: bool = False) -> int:
    """Leg de titels op de montage, in de gevraagde stijl. Geeft het aantal.

    Bestaande titels worden vervangen, andere overlays (eindkaart, ondertitels)
    blijven staan. Een stijlwissel betekent dus niet dat er opnieuw geregisseerd
    wordt — alleen dat de titels opnieuw gerenderd worden.
    """
    from . import titels as titels_mod

    spec = eis(stijl_id)
    oud = {o.id: (o.inhoud or {}).get("titelstijl") for o in edl.overlay
           if o.soort == "titel20"}
    edl.overlay = [o for o in edl.overlay if o.soort != "titel20"]

    clips = _clips(project)
    gevonden: list[dict] = []
    if clips and edl.video:
        gevonden = titels_mod.voorstel(
            [b.__dict__ for b in edl.video], clips, met_internet=met_internet
        )

    for i, t in enumerate(gevonden):
        edl.overlay.append(
            OverlayBlok(
                id=f"o-titel{i + 1}",
                soort="titel20",
                tijdlijn_start=t["tijdlijn_start"],
                duur=t["duur"],
                inhoud={
                    "titel": t["titel"],
                    "eyebrow": t["eyebrow"],
                    "onder": t["onder"],
                    "datum": _stempel(t.get("datum_iso") or ""),
                    "coords": _coords(t.get("lat"), t.get("lon")),
                    "nummer": i + 1,
                    "titelstijl": stijl_id,
                    "spec": json.dumps(spec, ensure_ascii=False),
                },
            )
        )
    edl.sorteer()

    # Een gerenderde overlay wordt op bestandsnaam hergebruikt. Bij een andere
    # stijl (of andere tekst) zou de oude MOV blijven liggen en zie je je keuze
    # niet terug.
    composities = paths.project_dir(project) / "composities"
    for o in edl.overlay:
        if o.soort == "titel20" and oud.get(o.id) != stijl_id:
            (composities / f"{o.id}.mov").unlink(missing_ok=True)
    for weg in set(oud) - {o.id for o in edl.overlay}:
        (composities / f"{weg}.mov").unlink(missing_ok=True)
    return len(gevonden)


# -- het voorbeeldbeeld ----------------------------------------------------


def _gedeeld(stijl_id: str) -> Path:
    """De machinebrede cache. Een voorbeeld hangt niet aan een project, dus
    hoeft de render maar één keer per machine te gebeuren."""
    return paths.steun_map() / "cache" / "titelvoorbeeld" / f"{stijl_id}.png"


def _in_project(project: str, stijl_id: str) -> Path:
    """De kopie in het project. Het asset-protocol van de app mag alleen bij de
    projectmap (`app/src-tauri/src/lib.rs`), dus daar moet het beeld staan."""
    return paths.project_dir(project) / "cache" / "titel" / f"{stijl_id}.png"


def _render_voorbeeld(stijl_id: str, doel: Path) -> None:
    from .graphics import Merk, render_overlay

    spec = eis(stijl_id)
    werk = doel.parent / "_render"
    # Eén frame is genoeg: de compositie zet zijn tijdlijn zelf op de helft als
    # `voorbeeld` aanstaat, en spoelt dus niet terug naar een leeg beeld.
    blok = OverlayBlok(
        id=f"v-{stijl_id}",
        soort="titel20",
        tijdlijn_start=0.0,
        duur=1 / 25,
        inhoud={
            **VOORBEELDTEKST,
            "titelstijl": stijl_id,
            "spec": json.dumps(spec, ensure_ascii=False),
            "voorbeeld": 1,
            # De animatie rekent met vier seconden, ook al renderen we er één
            # frame uit: anders valt de helft van de animatie ergens anders.
            "duur": 4.0,
        },
    )
    merk = Merk(id="voorbeeld", naam="voorbeeld", kleuren={}, typografie={},
                watermerken=[], veilige_marges={})
    mov = render_overlay(blok, merk, werk, breedte=RENDER_B, hoogte=RENDER_H, fps=25,
                         log=lambda *_: None)

    doel.parent.mkdir(parents=True, exist_ok=True)
    # Met alfa: de kaart in de app zet zijn eigen achtergrond eronder, net als
    # in het ontwerp.
    r = subprocess.run(
        [str(paths.ffmpeg()), "-y", "-loglevel", "error", "-i", str(mov),
         "-vf", f"scale={VOORBEELD_B}:{VOORBEELD_H}:flags=lanczos",
         "-frames:v", "1", "-pix_fmt", "rgba", str(doel)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0 or not doel.exists():
        raise TitelFout(f"Voorbeeld {stijl_id} faalde: {(r.stderr or '').strip()[-300:]}")
    mov.unlink(missing_ok=True)


def voorbeeld(stijl_id: str, project: str | None = None) -> Path:
    """Het voorbeeldbeeld van één stijl; rendert hem als hij nog niet bestaat."""
    eis(stijl_id)
    bron = _gedeeld(stijl_id)
    if not bron.exists() or bron.stat().st_size == 0:
        _render_voorbeeld(stijl_id, bron)
    if project is None:
        return bron
    doel = _in_project(project, stijl_id)
    if not doel.exists() or doel.stat().st_mtime < bron.stat().st_mtime:
        doel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bron, doel)
    return doel


def voorbeelden(project: str | None = None, *, melder=None) -> list[dict]:
    """Alle twintig voorbeelden, de ontbrekende erbij gerenderd.

    Duurt bij een lege cache een paar minuten (een browserrender per stijl),
    daarna is het een bestandskopie. Daarom meldt hij per stijl voortgang.
    """
    uit = []
    totaal = len(specs())
    for i, x in enumerate(specs()):
        try:
            pad: Path | None = voorbeeld(x["id"], project)
        except Exception as e:  # noqa: BLE001 — één kapotte stijl mag de rest niet blokkeren
            pad, fout = None, str(e)
        else:
            fout = ""
        uit.append({"id": x["id"], "naam": x["naam"], "animatie": x["animatie"],
                    "voorbeeld": str(pad) if pad else None, "fout": fout})
        if melder:
            melder("voortgang", {"werk": "titelvoorbeelden", "project": project or "",
                                 "stap": "voorbeelden", "gedaan": i + 1,
                                 "totaal": totaal, "id": x["id"],
                                 "tekst": f"Voorbeeld {x['naam']}",
                                 "percentage": round((i + 1) / totaal * 100, 1)})
    return uit


# Eén keer tegelijk. Twintig browserrenders naast elkaar starten omdat de
# interface tweemaal opent is een machine die stilstaat, niet een snellere.
_slot = threading.Lock()
_bezig = False


def is_bezig() -> bool:
    return _bezig


def in_achtergrond(project: str | None = None, *, melder=None) -> bool:
    """Maak de ontbrekende voorbeelden in een werkdraad. False = loopt al.

    Niet in de leeslus: een browserrender per stijl duurt seconden, en zolang
    zou de app op elk ander verzoek staan te wachten.
    """
    global _bezig
    with _slot:
        if _bezig:
            return False
        _bezig = True

    def werk():
        global _bezig
        try:
            lijstje = voorbeelden(project, melder=melder)
        except Exception as e:  # noqa: BLE001 — de app moet het horen, niet de stacktrace
            if melder:
                melder("fout", {"werk": "titelvoorbeelden", "project": project or "",
                                "fout": str(e), "soort": type(e).__name__})
            return
        finally:
            _bezig = False
        if melder:
            melder("klaar", {"werk": "titelvoorbeelden", "project": project or "",
                             "titelstijlen": lijstje})

    threading.Thread(target=werk, daemon=True).start()
    return True
