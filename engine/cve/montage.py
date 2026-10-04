"""Maak mijn video: muziek erbij, regie, render, nakijken.

De commandoregel heeft dit al (`cve maak`) en de oude Studio ook (de wizard).
Dit is dezelfde keten, maar aangeroepen vanuit de app: één werkdraad per
project die voortgang duwt over stdio in plaats van een balk die gepolld wordt.

Niets hier bedenkt zelf iets. De regie komt uit `director/`, het renderen uit
`render.py`, het nakijken uit `review.py`, de weging van de balk uit
`voortgang.py`. Wat hier staat is de rij waarin ze langskomen en wat de app
ervan te zien krijgt.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from . import looks, media, montagestijl, paths, projecten, stijlkeuze, titelstijl, voortgang
from . import stijl as stijl_mod
from .director.preset import VORMEN

# De vormen die de renderer écht kan. Uit `director/preset.py`, want daar
# staat de enige tabel die de canvasmaat bepaalt — een vorm die daar niet in
# staat valt stil terug op 16:9, en dan krijgt de gebruiker iets anders dan
# hij koos. Sinds 04-10-2026 staat 4:5 (Instagram-portret) er ook in.
def vormen() -> list[dict]:
    return [
        {"naam": naam, "breedte": b, "hoogte": h} for naam, (b, h) in VORMEN.items()
    ]


def _analyse(project: str) -> dict | None:
    pad = paths.PROJECTEN / project / "analysis.json"
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def stijlen(project: str) -> dict:
    """Beide stijllagen, wat bij dit materiaal past, en de vormen.

    `stijlen` is het **soort beelden** (vijf, wordt herkend), `montagestijlen`
    is het **snijritme** (veertien, kiest de gebruiker). Zie PLAN-v2.md §4 en
    `montagestijl.py` voor waarom dat twee dingen zijn.
    """
    lijst = [
        {
            "naam": pad.stem,
            "titel": stijl_mod.laad(pad.stem, paths.STYLES).titel,
            "omschrijving": stijlkeuze.UITLEG.get(
                pad.stem, stijl_mod.laad(pad.stem, paths.STYLES).omschrijving
            ),
        }
        for pad in sorted(paths.STYLES.glob("*.md"))
    ]
    uit: dict = {
        "stijlen": lijst,
        "montagestijlen": [m.naar_dict() for m in montagestijl.alle(paths.STYLES)],
        "banden": montagestijl.BANDEN,
        # De twintig titelstijlen. `voorbeeld` is leeg tot het beeld gemaakt is;
        # dat kost een render per stijl en gaat daarom via `titel.voorbeelden`.
        "titelstijlen": titelstijl.lijst(project),
        "titel_gekozen": titelstijl.gekozen(project),
        "vormen": vormen(),
        "herkend": None,
        "montage_herkend": None,
    }
    analyse = _analyse(project)
    if analyse:
        v = stijlkeuze.kies(analyse)
        uit["herkend"] = v.stijl
        # De montagestijl die standaard bij dat soort beelden hoort. Een
        # voorstel, niet de wet: één klik en de gebruiker heeft iets anders.
        uit["montage_herkend"] = montagestijl.standaard_bij(v.stijl)
        uit["zekerheid"] = v.zekerheid
        uit["uitleg"] = v.zin()
        uit["gemeten"] = v.gemeten
    return uit


# -- muziek ----------------------------------------------------------------


def _huidige_muziek(project: str) -> Path | None:
    sporen = media.vind_muziek(paths.PROJECTEN / project / "muziek")
    return sporen[0] if sporen else None


def zet_muziek(project: str, pad: str) -> Path:
    """Neem een audiobestand op als de muziek van dit project.

    Een kopie in `muziek/`, net als de upload van de oude Studio; het
    bronbestand blijft onaangeroerd (regel 4). Een vorige track gaat naar
    `muziek/_vorige/` in plaats van weg: `vind_muziek()` kijkt niet in
    submappen, dus hij telt niet meer mee, maar hij is wel terug te halen.
    """
    bron = Path(pad).expanduser()
    if not bron.is_file():
        raise ValueError(f"Geen bestand gevonden: {bron}")
    if bron.suffix.lower() not in media.AUDIO_EXTENSIES:
        raise ValueError(f"Bestandstype {bron.suffix or '(onbekend)'} is geen muziek.")

    mdir = paths.project_dir(project) / "muziek"
    mdir.mkdir(parents=True, exist_ok=True)
    doel = mdir / bron.name
    if doel.exists() and projecten._zelfde_bestand(bron, doel):
        return doel

    vorige = mdir / "_vorige"
    for q in media.vind_muziek(mdir):
        vorige.mkdir(exist_ok=True)
        shutil.move(str(q), str(_vrije_naam(vorige, q.name)))
    shutil.copy2(bron, doel)
    return doel


def _vrije_naam(map_: Path, naam: str) -> Path:
    """`song.wav`, of `song-2.wav` als die er al staat.

    Het archief mag nooit iets overschrijven: drie bestanden die alle drie
    `song.wav` heten zijn drie verschillende nummers, en `_vorige/` is het
    enige wat ervan over is.
    """
    stam, achter = Path(naam).stem, Path(naam).suffix
    kandidaat = map_ / naam
    n = 2
    while kandidaat.exists():
        kandidaat = map_ / f"{stam}-{n}{achter}"
        n += 1
    return kandidaat


def _vingerafdruk(track: Path) -> dict:
    """Waaraan je ziet dat dit nog dezelfde track is.

    De naam alleen is niet genoeg: wie `song.wav` vervangt door een ander
    nummer met dezelfde naam, hield anders de beats, de BPM en de duur van
    het oude — en dan ligt de montage op beats die er niet meer zijn.
    Grootte plus wijzigingsmoment is gratis en gaat er in de praktijk niet
    naast; `shutil.copy2` neemt beide van het bronbestand over.
    ponytail: geen hash. Pas nodig als iemand twee tracks van exact dezelfde
    grootte én hetzelfde wijzigingsmoment kan aanleveren.
    """
    st = track.stat()
    return {"bestand": track.name, "bytes": st.st_size, "gewijzigd": round(st.st_mtime, 3)}


def muziekstand(project: str) -> dict | None:
    """BPM en duur van de huidige track, als de analyse er al is.

    Bron is `analysis.json`; een tweede administratie van hetzelfde zou
    kunnen gaan afwijken. Klopt de vingerafdruk niet, dan hoort de meting bij
    een vorige track en is hij dus onbruikbaar. Een meting van vóór
    03-10-2026 heeft nog geen vingerafdruk en wordt daarom één keer opnieuw
    gedaan — dat is goedkoper dan hem op zijn woord geloven.
    """
    track = _huidige_muziek(project)
    if track is None:
        return None
    analyse = _analyse(project) or {}
    m = analyse.get("muziek") or {}
    nu = _vingerafdruk(track)
    if any(m.get(k) != v for k, v in nu.items()):
        return None
    return {"bestand": track.name, "bpm": m.get("bpm"), "duur": m.get("duur")}


# Eén meting tegelijk. De app kan "muziek kiezen" en "maak mijn video" kort
# na elkaar sturen; schreven die allebei `analysis.json`, dan is de analyse
# van het hele project weg.
_muziekslot = threading.Lock()


def analyseer_muziek(project: str) -> dict:
    """Meet de huidige track en zet de meting in `analysis.json`.

    Zonder deze stap houdt een project met nieuwe muziek het snijraster van de
    oude: de montage ligt dan op beats die er niet meer zijn.
    """
    from .analyze import muziek as muziek_mod

    track = _huidige_muziek(project)
    if track is None:
        raise ValueError("Dit project heeft nog geen muziek.")

    with _muziekslot:
        # Wie hier als tweede binnenkomt, vindt de meting van de eerste.
        bestaand = muziekstand(project)
        if bestaand is not None:
            return bestaand
        return _meet_en_bewaar(project, track, muziek_mod)


def _meet_en_bewaar(project: str, track: Path, muziek_mod) -> dict:
    m = muziek_mod.analyseer(track)
    from dataclasses import asdict

    blok = asdict(m)
    blok["snijraster"] = muziek_mod.snijraster(m)
    blok.update(_vingerafdruk(track))

    pad = paths.PROJECTEN / project / "analysis.json"
    analyse = _analyse(project)
    if analyse is not None:
        analyse["muziek"] = blok
        pad.write_text(json.dumps(analyse, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"bestand": track.name, "bpm": m.bpm, "duur": m.duur}


def muziek_in_achtergrond(project: str, melder=None) -> threading.Thread:
    """Meet de muziek in een werkdraad en meld het resultaat.

    Niet in de leeslus: librosa doet seconden over een track van drie minuten,
    en zolang zou de app op elk ander verzoek staan te wachten.
    """

    def werk():
        try:
            data = analyseer_muziek(project)
        except Exception as e:  # noqa: BLE001 — de app moet het horen, niet de stacktrace
            if melder:
                melder("fout", {"werk": "muziek", "project": project,
                                "fout": str(e), "soort": type(e).__name__})
            return
        if melder:
            melder("klaar", {"werk": "muziek", "project": project, "muziek": data})

    draad = threading.Thread(target=werk, daemon=True)
    draad.start()
    return draad


# -- de hele montage -------------------------------------------------------


def _uitgesloten(project: str) -> list[str]:
    """Clip-id's van de clips die de gebruiker in stap 1 uitgezet heeft.

    `selectie.json` bewaart bestandsnamen (die zijn stabiel), de regisseur
    filtert op clip-id. Zonder deze omzetting komen uitgezette clips alsnog in
    de montage.
    """
    uit = projecten.selectie(project)
    if not uit:
        return []
    try:
        ing = json.loads(
            (paths.PROJECTEN / project / "ingest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    return [c["id"] for c in ing.get("clips") or [] if c["bestand"] in uit]


def review_regels(rapport: dict) -> list[dict]:
    """Het reviewrapport als lijst voor de interface."""
    return [
        {
            "naam": b["code"],
            "ok": b["ernst"] != "fout",
            "ernst": b["ernst"],
            "tekst": b["boodschap"],
        }
        for b in rapport.get("bevindingen") or []
    ]


def laatste_video(project: str) -> dict | None:
    """De nieuwste render van dit project, met het reviewrapport erbij."""
    pdir = paths.PROJECTEN / project
    renders = sorted(
        (pdir / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not renders:
        return None
    bestand = renders[0]
    try:
        duur = round(media.probe(bestand).duur, 3)
    except Exception:  # noqa: BLE001 — een halve render mag de lijst niet slopen
        duur = 0.0

    review = None
    try:
        rap = json.loads((pdir / "review.json").read_text(encoding="utf-8"))
        if Path(rap.get("bestand", "")).name == bestand.name:
            review = review_regels(rap)
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "project": project,
        "video": str(bestand),
        "naam": bestand.name,
        "duur": duur,
        "wanneer": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(bestand.stat().st_mtime)
        ) + "Z",
        "bytes": bestand.stat().st_size,
        "review": review,
    }


def brief_van(stijl: str, vorm: str, duur: float | None, montage: str = "") -> dict:
    """De keuzes uit Stijl die samen de montage bepalen.

    Komt zo in `edl.json` te staan, zodat `regie_nodig()` later kan zien of er
    sindsdien iets veranderd is. `montage` hoort er sinds 03-10-2026 bij: een
    andere montagestijl is een ander snijritme en dus een andere montage.
    """
    return {
        "stijl": str(stijl),
        "montage": str(montage or montagestijl.standaard_bij(str(stijl))),
        "vorm": str(vorm),
        "duur": None if duur is None else round(float(duur), 3),
    }


def regie_nodig(
    project: str, *, stijl: str, vorm: str, duur: float | None, montage: str = ""
) -> bool:
    """Moet de montage opnieuw bedacht worden, of mag `edl.json` blijven staan?

    De regel staat hier en niet in de interface, want de interface kan hem dan
    per ongeluk overslaan — en dan gooit "Exporteer op volle kwaliteit" alles
    weg wat er in stap 4 met de hand is bijgesteld. Opnieuw regisseren mag
    alleen als er nog geen montage is, of als er in Stijl bewust een andere
    stijl, vorm of lengte gekozen is.
    """
    edlpad = paths.project_dir(project) / "edl.json"
    if not edlpad.exists():
        return True
    from .edl import EDL

    try:
        bestaand = EDL.lees(edlpad)
    except (OSError, ValueError, KeyError, TypeError):
        return True
    if not bestaand.video:
        return True
    # Een montage van vóór 03-10-2026 heeft nog geen brief; die wordt één keer
    # opnieuw bedacht en draagt hem daarna wel.
    return bestaand.brief != brief_van(stijl, vorm, duur, montage)


def maak_video(
    project: str,
    *,
    stijl: str = "reis",
    montage: str = "",
    titel: str = "",
    vorm: str = "16:9",
    duur: float | None = None,
    kwaliteit: str = "preview",
    regie: bool | None = None,
    melder=None,
) -> threading.Thread:
    """Regie, render en nakijken in één beweging, in een werkdraad.

    `regie=None` (het normale geval) laat `regie_nodig()` beslissen: de
    montage die er ligt blijft staan tenzij er in Stijl een andere stijl, vorm
    of lengte gekozen is. `regie=False` rendert `edl.json` altijd zoals hij er
    ligt; `regie=True` bedenkt hem altijd opnieuw. Wie in stap 4 shots heeft
    bijgesteld ziet die wijzigingen anders bij de eerste klik op "Maak video"
    weer verdwijnen onder een verse regie.

    `melder(soort, data)` krijgt "voortgang", "klaar" of "fout". De
    percentages komen uit `voortgang.py`, zodat de balk dezelfde weging houdt
    als in de Studio: blokken renderen is het zwaarste deel, nakijken het
    lichtste.
    """
    from .director import Brief, kies_regisseur
    from .render import RenderOpties
    from .render import render as _render
    from .review import review as _review

    if vorm not in VORMEN:
        raise ValueError(f"Vorm {vorm!r} kan niet. Kies uit: {', '.join(VORMEN)}")
    titelkeuze = str(titel or titelstijl.standaard())
    titelstijl.eis(titelkeuze)
    if kwaliteit not in ("preview", "eind"):
        raise ValueError(f"Kwaliteit {kwaliteit!r} kan niet. Kies 'preview' of 'eind'.")
    pdir = paths.project_dir(project)
    if _analyse(project) is None:
        raise ValueError("Dit project is nog niet geanalyseerd.")
    if _huidige_muziek(project) is None:
        raise ValueError("Dit project heeft nog geen muziek.")
    opnieuw = (
        regie_nodig(project, stijl=stijl, vorm=vorm, duur=duur, montage=montage)
        if regie is None
        else bool(regie)
    )
    if not projecten.neem_bezig(project, "De montage bedenken…"):
        raise RuntimeError(f"Er loopt al werk aan dit project: {projecten.is_bezig(project)}")

    vg = voortgang
    vg.start(project, vg.RENDER_FASEN)

    def meld(fase: str, gedaan: int = 0, totaal: int = 0) -> None:
        vg.meld(project, fase, gedaan, totaal)
        stand = vg.stand(project) or {}
        projecten.zet_bezig(project, stand.get("tekst") or fase)
        if melder:
            melder(
                "voortgang",
                {
                    "werk": "maakvideo",
                    "project": project,
                    "stap": fase,
                    "gedaan": gedaan,
                    "totaal": totaal,
                    "percentage": stand.get("percentage", 0.0),
                    "resterend": stand.get("resterend"),
                    "tekst": stand.get("tekst") or fase,
                },
            )

    # Wat de render onderweg tegenkwam en niet zelf kan oplossen — titels die
    # niet getekend konden worden, bijvoorbeeld. Gaat mee in de `klaar`-
    # gebeurtenis, zodat Exporteren het kan tonen in plaats van dat het stil in
    # het log blijft hangen.
    waarschuwingen: list[str] = []

    def werk():
        try:
            meld("voorbereiden", 0, 1)
            # Nieuwe muziek betekent een ander snijraster. Dit is goedkoop als
            # de meting al klopt en noodzakelijk als dat niet zo is.
            if muziekstand(project) is None:
                analyseer_muziek(project)
            edlpad = pdir / "edl.json"
            if not opnieuw and edlpad.exists():
                # Stap 4 heeft de montage al; hier alleen nog renderen. Niets
                # schrijven dus: elke regel die we hier zouden zetten is een
                # regel die de gebruiker net zelf heeft gekozen.
                from .edl import EDL

                eigen = EDL.lees(edlpad)
                # De titels zijn de ene uitzondering: een andere titelstijl is
                # geen andere montage, dus `regie_nodig()` ziet hem niet, maar
                # hij moet wel in de video komen. Alleen `overlay` verandert
                # hier; de shots blijven staan zoals de gebruiker ze zette.
                titelstijl.zet_op(eigen, project, titelkeuze)
                eigen.schrijf(edlpad)
                uitleg = (
                    f"Jouw montage: {len(eigen.video)} shots, {eigen.duur:.1f}s. "
                    f"De regie is gelaten zoals hij stond."
                )
            else:
                analyse = _analyse(project)
                voorstel = kies_regisseur("preset").stel_voor(
                    analyse,
                    Brief(doelduur=duur, stijl=stijl, montage=montage, vorm=vorm,
                          uitgesloten=_uitgesloten(project)),
                )
                if not voorstel.edl.video:
                    # Geen shots betekent: geen enkel segment paste op het ritme
                    # van deze stijl. De regisseur weet waarom; dat is wat de
                    # gebruiker moet horen, niet "0 shots".
                    raise ValueError(
                        " ".join(voorstel.waarschuwingen)
                        or "Te weinig bruikbaar materiaal voor een montage."
                    )
                # De look is een keuze van de gebruiker en de regisseur weet er
                # niets van; zonder deze regel is hij na elke montage weer weg.
                looks.pas_toe(voorstel.edl, looks.keuze(project))
                titelstijl.zet_op(voorstel.edl, project, titelkeuze)
                voorstel.edl.brief = brief_van(stijl, vorm, duur, montage)
                voorstel.edl.schrijf(edlpad)
                uitleg = voorstel.uitleg
            meld("voorbereiden", 1, 1)

            uit = _render(
                project,
                opties=RenderOpties(modus=kwaliteit),
                log=lambda *_: None,
                melden=lambda fase, k=0, t=0: meld(fase, k, t),
                waarschuwingen=waarschuwingen,
            )
            meld("nakijken", 0, 1)
            rapport = _review(project, bestand=uit, log=lambda *_: None).naar_dict()
            meld("nakijken", 1, 1)
        except Exception as e:  # noqa: BLE001 — elke fout gaat als gebeurtenis terug
            import sys
            import traceback

            # De app krijgt alleen de melding; zonder dit is de stacktrace van
            # een werkdraad nergens meer te zien.
            traceback.print_exc(file=sys.stderr)
            vg.mislukt(project, str(e))
            projecten.zet_bezig(project, None)
            if melder:
                melder("fout", {"werk": "maakvideo", "project": project,
                                "fout": str(e), "soort": type(e).__name__})
            return

        projecten.zet_bezig(project, None)
        vg.klaar(project, bestand=uit.name, review=rapport)
        if melder:
            melder(
                "klaar",
                {
                    "werk": "maakvideo",
                    "project": project,
                    "video": str(uit),
                    "duur": round(media.probe(uit).duur, 3),
                    "geslaagd": rapport["geslaagd"],
                    "review": review_regels(rapport),
                    "uitleg": uitleg,
                    "waarschuwingen": waarschuwingen,
                },
            )

    draad = threading.Thread(target=werk, daemon=True)
    draad.start()
    return draad
