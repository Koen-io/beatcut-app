"""Engine als sidecar: JSON-RPC over stdin/stdout, één bericht per regel.

De BeatCut 2-app (Tauri) start dit proces en praat er alleen hiermee. Geen
poort: geen firewallmelding, geen botsing, en het proces sterft met de app.

    verzoek   {"id": 1, "methode": "doctor", "params": {}}
    antwoord  {"id": 1, "resultaat": {...}}
    fout      {"id": 1, "fout": {"bericht": "...", "soort": "ValueError"}}
    gebeurtenis  {"gebeurtenis": "voortgang", "data": {...}}   (ongevraagd, geen id)

Een gebeurtenis heeft geen `id`: daaraan ziet de Rust-kant het verschil tussen
een antwoord op een vraag en een duwtje van de engine zelf.

stdout is uitsluitend voor het protocol. Alles wat engine-code print, gaat
tijdens een verzoek naar stderr, anders breekt één losse print() de app.
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any

from . import __version__

PROTOCOL = 1

# Eén deur naar stdout. Antwoorden komen van de leeslus, gebeurtenissen uit een
# werkdraad; zonder slot schuiven twee regels door elkaar en is het protocol weg.
_schrijfslot = threading.Lock()
_uit: Any = None


def _schrijf(bericht: dict[str, Any]) -> None:
    # `sys.__stdout__` als terugval: `verwerk()` zet `sys.stdout` tijdelijk op
    # stderr, en een werkdraad mag daar niet in meegesleurd worden.
    doel = _uit if _uit is not None else sys.__stdout__
    regel = json.dumps(bericht, ensure_ascii=False) + "\n"
    with _schrijfslot:
        # Zelf de bytes maken in plaats van de stroom laten kiezen: een pijp
        # op Windows staat standaard op cp1252, en dan wordt een projectnaam
        # als `José` andere bytes dan UTF-8. De leesdraad in Rust verwacht
        # UTF-8 en valt stil op de rest. Dit is de enige schrijver naar deze
        # stroom en hij flusht altijd, dus tekst en bytes bijten elkaar niet.
        ruw = getattr(doel, "buffer", None)
        if ruw is None:
            doel.write(regel)
            doel.flush()
        else:
            ruw.write(regel.encode("utf-8"))
            ruw.flush()


def gebeurtenis(naam: str, data: dict[str, Any]) -> None:
    """Ongevraagd bericht naar de app: voortgang, klaar, fout."""
    _schrijf({"gebeurtenis": naam, "data": data})


_Methode = Callable[[dict[str, Any]], Any]
METHODES: dict[str, _Methode] = {}


def methode(naam: str) -> Callable[[_Methode], _Methode]:
    def registreer(fn: _Methode) -> _Methode:
        METHODES[naam] = fn
        return fn

    return registreer


@methode("hallo")
def _hallo(_: dict[str, Any]) -> dict[str, Any]:
    return {"engine": "beatcut", "versie": __version__, "protocol": PROTOCOL, "methodes": sorted(METHODES)}


@methode("doctor")
def _doctor(_: dict[str, Any]) -> dict[str, Any]:
    from .doctor import checks

    lijst = [
        {"naam": c.naam, "ok": c.ok, "detail": c.detail, "vereist": c.vereist} for c in checks()
    ]
    fouten = sum(1 for c in lijst if c["vereist"] and not c["ok"])
    return {"ok": fouten == 0, "fouten": fouten, "checks": lijst}


@methode("projecten")
def _projecten(_: dict[str, Any]) -> list[dict[str, Any]]:
    from .projecten import alle, naar_dict

    return [naar_dict(s) for s in alle()]


def _vereist(params: dict[str, Any], sleutel: str) -> str:
    waarde = str(params.get(sleutel) or "").strip()
    if not waarde:
        raise ValueError(f"'{sleutel}' ontbreekt")
    return waarde


@methode("bezig")
def _bezig(_: dict[str, Any]) -> dict[str, Any]:
    """Loopt er ergens werk? Eén vraag over alle projecten heen.

    De app stelt hem vóór het installeren van een update: op Windows sluit de
    updater de app meteen af, en dat mag nooit midden in een render, een
    analyse of een muziekgeneratie gebeuren.
    """
    from . import muziekgen, muziekinstall, onderdelen, projecten

    werk = [{"project": n, "tekst": t} for n, t in sorted(projecten.alles_bezig().items())]
    for n in sorted(muziekgen.bezige_projecten()):
        werk.append({"project": n, "tekst": "Muziek componeren…"})
    if muziekinstall.is_bezig():
        werk.append({"project": "", "tekst": "Muziekmodel installeren…"})
    if onderdelen.is_bezig():
        werk.append({"project": "", "tekst": "Titels klaarzetten…"})
    return {"bezig": bool(werk), "werk": werk}


@methode("project.maak")
def _project_maak(p: dict[str, Any]) -> dict[str, Any]:
    from .projecten import maak, naar_dict

    return naar_dict(maak(_vereist(p, "naam")))


@methode("project.voegtoe")
def _project_voegtoe(p: dict[str, Any]) -> dict[str, Any]:
    from .projecten import naar_dict, status, voeg_toe

    project = _vereist(p, "project")
    paden = p.get("paden") or []
    if not isinstance(paden, list):
        raise TypeError("'paden' moet een lijst zijn")
    bestanden = voeg_toe(project, [str(q) for q in paden])
    return {"bestanden": bestanden, "status": naar_dict(status(project))}


@methode("project.verwerk")
def _project_verwerk(p: dict[str, Any]) -> dict[str, Any]:
    from . import projecten as mod

    project = _vereist(p, "project")
    bezig = mod.is_bezig(project)
    if bezig:
        return {"gestart": False, "bezig": bezig}
    mod.verwerk(
        project,
        stijl=str(p.get("stijl") or "landschap"),
        opnieuw=bool(p.get("opnieuw")),
        melder=gebeurtenis,
    )
    return {"gestart": True}


@methode("project.clips")
def _project_clips(p: dict[str, Any]) -> list[dict[str, Any]]:
    from .projecten import clips

    return clips(_vereist(p, "project"))


@methode("clip.zet")
def _clip_zet(p: dict[str, Any]) -> dict[str, Any]:
    from .projecten import zet_selectie

    project = _vereist(p, "project")
    clip = _vereist(p, "clip")
    if "aan" not in p:
        raise ValueError("'aan' ontbreekt")
    uit = zet_selectie(project, clip, bool(p["aan"]))
    return {"clip": clip, "aan": clip not in uit, "uit": sorted(uit)}


@methode("project.muziek")
def _project_muziek(p: dict[str, Any]) -> dict[str, Any] | None:
    """Zet een audiobestand als de muziek van het project.

    Is de meting er al, dan komt BPM en duur meteen terug. Zo niet, dan loopt
    de meting in een werkdraad en komt hij als `klaar`-gebeurtenis met
    `werk: "muziek"`.

    Zonder `pad` is dit alleen lezen: wat ligt er nu, en wat is er gemeten.
    De interface heeft dat nodig om de huidige track te kunnen tonen zonder
    hem opnieuw te zetten.
    """
    from . import montage

    project = _vereist(p, "project")
    if not p.get("pad"):
        return montage.muziekstand(project)
    pad = montage.zet_muziek(project, str(p["pad"]))
    stand = montage.muziekstand(project)
    if stand is not None:
        return {"bestand": pad.name, "gestart": False, **stand}
    montage.muziek_in_achtergrond(project, melder=gebeurtenis)
    return {"bestand": pad.name, "gestart": True, "bpm": None, "duur": None}


@methode("muziek.status")
def _muziek_status(p: dict[str, Any]) -> dict[str, Any]:
    """Is het muziekmodel er, waar staat het, hoe groot — plus de genres.

    Met `project` erbij komt ook terug wat er voor dat project al gegenereerd
    is, zodat de interface de varianten van een vorige sessie kan tonen.
    """
    from . import muziekgen, muziekinstall

    uit = muziekgen.status()
    uit["installeren_bezig"] = muziekinstall.is_bezig()
    if p.get("project"):
        project = str(p["project"])
        uit["varianten"] = muziekgen.bestaande(project)
        uit["bezig"] = muziekgen.is_bezig(project)
    return uit


@methode("muziek.installeer")
def _muziek_installeer(_: dict[str, Any]) -> dict[str, Any]:
    """Haal het muziekmodel op (ongeveer 11 GB). Antwoordt meteen.

    De voortgang komt als gebeurtenis met `werk: "muziekinstall"`, net als bij
    een render. Loopt er al een installatie, dan is `gestart` onwaar en gebeurt
    er niets — twee keer tegelijk downloaden naar dezelfde map gaat mis.
    """
    from . import muziekinstall

    return {"gestart": muziekinstall.in_achtergrond(melder=gebeurtenis)}


@methode("muziek.installeer_stop")
def _muziek_installeer_stop(_: dict[str, Any]) -> dict[str, Any]:
    """Breek de installatie af. Wat er al staat blijft staan en is te hervatten."""
    from . import muziekinstall

    return {"gestopt": muziekinstall.stop_installatie()}


@methode("muziek.genereer")
def _muziek_genereer(p: dict[str, Any]) -> dict[str, Any]:
    """Start het genereren. Antwoordt meteen; de rest komt als gebeurtenis.

    Zonder `bpm` kiest de engine er een bij de stijl en het genre. Dat hoort
    hier en niet in de interface: die weet niet dat `luchtvaart` lange shots
    heeft en dus een laag tempo wil.
    """
    from . import muziekgen

    project = _vereist(p, "project")
    bpm = p.get("bpm")
    duur = p.get("duur")
    gestart = muziekgen.in_achtergrond(
        project,
        melder=gebeurtenis,
        genre=str(p.get("genre") or "House"),
        stemming=str(p["stemming"]) if p.get("stemming") else None,
        bpm=int(bpm) if bpm else None,
        duur=float(duur) if duur else 30.0,
        zang=bool(p.get("zang")),
        varianten=int(p.get("varianten") or 3),
        stijl=str(p["stijl"]) if p.get("stijl") else None,
        # Alleen de test zet dit: met een vaste seed is het resultaat
        # herhaalbaar en is de testuitslag geen dobbelsteen.
        seed=int(p["seed"]) if p.get("seed") is not None else None,
    )
    return {"gestart": gestart, "bezig": not gestart}


@methode("muziek.kies")
def _muziek_kies(p: dict[str, Any]) -> dict[str, Any] | None:
    """Zet een gegenereerde variant als de muziek van het project.

    Loopt over dezelfde route als `project.muziek`: kopie in `muziek/`, de
    vorige track naar `muziek/_vorige/`, en de BPM-meting erachteraan. Een
    tweede route zou een tweede administratie betekenen.
    """
    _vereist(p, "pad")
    return _project_muziek(p)


@methode("onderdelen.status")
def _onderdelen_status(_: dict[str, Any]) -> dict[str, Any]:
    """Staan node, HyperFrames en de browser klaar om titels te tekenen?

    De app vraagt dit bij het opstarten. Ontbreekt er iets en is er internet,
    dan haalt hij het op de achtergrond op; ontbreekt het nog bij Exporteren
    terwijl er titels in de montage staan, dan hoort de gebruiker dat te zien
    vóór de render — niet achteraf aan een video zonder titels.
    """
    from . import onderdelen

    return onderdelen.status()


@methode("onderdelen.installeer")
def _onderdelen_installeer(_: dict[str, Any]) -> dict[str, Any]:
    """Haal op wat er mist (ongeveer 400 MB). Antwoordt meteen.

    De voortgang komt als gebeurtenis met `werk: "onderdelen"`. Loopt er al
    een installatie, dan is `gestart` onwaar en gebeurt er niets.
    """
    from . import onderdelen

    return {"gestart": onderdelen.in_achtergrond(melder=gebeurtenis)}


@methode("onderdelen.installeer_stop")
def _onderdelen_installeer_stop(_: dict[str, Any]) -> dict[str, Any]:
    """Breek het klaarzetten af. Wat er al staat blijft staan en is te hervatten."""
    from . import onderdelen

    return {"gestopt": onderdelen.stop_installatie()}


@methode("project.stijlen")
def _project_stijlen(p: dict[str, Any]) -> dict[str, Any]:
    from . import montage

    return montage.stijlen(_vereist(p, "project"))


@methode("titel.voorbeelden")
def _titel_voorbeelden(p: dict[str, Any]) -> dict[str, Any]:
    """Maak de voorbeeldbeelden van de twintig titelstijlen. Antwoordt meteen.

    Bij een lege cache is dit een browserrender per stijl en dus een paar
    minuten werk; daarna een bestandskopie. De voortgang en de uitkomst komen
    als gebeurtenis terug, net als bij het genereren van muziek.
    """
    from . import titelstijl

    project = str(p["project"]) if p.get("project") else None
    gestart = titelstijl.in_achtergrond(project, melder=gebeurtenis)
    return {"gestart": gestart, "bezig": not gestart,
            "titelstijlen": titelstijl.lijst(project)}


@methode("project.looks")
def _project_looks(p: dict[str, Any]) -> dict[str, Any]:
    """De catalogus, de sfeerfilters en wat er voor dit project gekozen is.

    Alle sterktes zijn hier 0..1, net als in `edl.Afwerking`. De schuiven in
    de interface staan op 0..100; die omrekening doet de interface, zodat er
    maar één schaal over de draad gaat.
    """
    from . import looks

    return {
        "looks": looks.lijst(),
        "sferen": looks.SFEREN,
        "gekozen": looks.keuze(_vereist(p, "project")),
    }


@methode("project.look.zet")
def _project_look_zet(p: dict[str, Any]) -> dict[str, Any]:
    from . import looks

    return looks.zet(
        _vereist(p, "project"),
        str(p.get("id") or "geen"),
        float(p.get("sterkte", 1.0)),
        p.get("afwerking"),
    )


@methode("project.look.voorbeeld")
def _project_look_voorbeeld(p: dict[str, Any]) -> dict[str, Any]:
    """Eén frame door dezelfde keten als de render, als PNG op schijf."""
    from . import looks

    return looks.voorbeeld(
        _vereist(p, "project"),
        str(p.get("id") or "geen"),
        float(p.get("sterkte", 1.0)),
        p.get("afwerking"),
        clip=str(p["clip"]) if p.get("clip") else None,
        breedte=int(p.get("breedte") or 0),
    )


@methode("licenties")
def _licenties(p: dict[str, Any]) -> dict[str, Any]:
    """De lijst met software en gegevens van derden (installer/DERDEN.md)."""
    from . import paths

    for pad in (paths.ROOT / "DERDEN.md", paths.ROOT / "installer" / "DERDEN.md"):
        if pad.exists():
            return {"tekst": pad.read_text(encoding="utf-8")}
    return {"tekst": "De licentielijst ontbreekt in deze build."}


@methode("project.titels")
def _project_titels(p: dict[str, Any]) -> dict[str, Any]:
    """De overlays met hun variabelen, voor de live voorvertoning.

    `project.montage` geeft alleen de tekst van een titel; de speler heeft de
    hele vormgeving nodig om dezelfde compositie te kunnen draaien als de
    render. Zie `engine/cve/titelweb.py`.
    """
    from . import titelweb

    return titelweb.voor_speler(_vereist(p, "project"))


@methode("look.lut")
def _look_lut(p: dict[str, Any]) -> dict[str, Any]:
    """Het `.cube`-bestand van een look als tekst, voor de live voorvertoning.

    De speler in de app kan `looks/` niet zelf lezen: het asset-protocol van
    Tauri mag alleen bij de projectmap. Daarom gaat de tabel over de RPC. Het is
    ~1 MB tekst en hij wordt één keer per look opgehaald.

    `cube` is `null` bij `geen` en `origineel`; de speler gebruikt dan zijn
    identiteitstabel, net als `compositor/src/lut.rs` doet.
    """
    from . import looks

    look_id = str(p.get("id") or "geen")
    pad = looks.lut_pad(look_id)
    return {
        "id": look_id,
        "cube": pad.read_text(encoding="utf-8") if pad is not None else None,
    }


@methode("project.montage")
def _project_montage(p: dict[str, Any]) -> dict[str, Any] | None:
    """De montage uit `edl.json`, met tel-raster, golfvorm en beeldjes.

    `null` als er nog geen montage is — dan heeft stap 4 niets te tonen en
    stuurt de interface de gebruiker terug naar Stijl.
    """
    from . import bijwerken

    return bijwerken.montage(_vereist(p, "project"))


@methode("project.clip.voorkeur")
def _project_clip_voorkeur(p: dict[str, Any]) -> dict[str, Any]:
    """"Moet erin" of "nooit gebruiken" op een clip; `soort: null` haalt hem weg."""
    from . import bijwerken

    soort = p.get("soort")
    return bijwerken.voorkeur(
        _vereist(p, "project"), _vereist(p, "clip"), str(soort) if soort else None
    )


@methode("project.shot.zet")
def _project_shot_zet(p: dict[str, Any]) -> dict[str, Any]:
    """Eén shot bijwerken. De tijdlijn verschuift niet; alleen het beeld erin."""
    from . import bijwerken

    snelheid = p.get("snelheid")
    bron_in = p.get("bron_in")
    return bijwerken.zet_shot(
        _vereist(p, "project"),
        _vereist(p, "shot"),
        snelheid=float(snelheid) if snelheid is not None else None,
        bron_in=float(bron_in) if bron_in is not None else None,
    )


@methode("project.regisseer")
def _project_regisseer(p: dict[str, Any]) -> dict[str, Any]:
    """Alleen de regie opnieuw, zonder render. Antwoordt met de nieuwe montage."""
    from . import bijwerken

    duur = p.get("duur")
    return bijwerken.regisseer(
        _vereist(p, "project"),
        stijl=str(p["stijl"]) if p.get("stijl") else None,
        montagestijl=str(p["montage"]) if p.get("montage") else None,
        vorm=str(p["vorm"]) if p.get("vorm") else None,
        duur=float(duur) if duur else None,
    )


@methode("project.maakvideo")
def _project_maakvideo(p: dict[str, Any]) -> dict[str, Any]:
    from . import montage

    duur = p.get("duur")
    montage.maak_video(
        _vereist(p, "project"),
        stijl=str(p.get("stijl") or "reis"),
        # Leeg betekent: de montagestijl die bij dit soort beelden hoort.
        montage=str(p.get("montage") or ""),
        # Leeg betekent: de eerste titelstijl uit de catalogus.
        titel=str(p.get("titel") or ""),
        vorm=str(p.get("vorm") or "16:9"),
        duur=float(duur) if duur else None,
        kwaliteit=str(p.get("kwaliteit") or "preview"),
        # Zonder `regie` beslist de engine: alleen een andere stijl, vorm of
        # lengte dan waarmee `edl.json` bedacht is leidt tot een nieuwe regie.
        # Stap 4 stuurt daarnaast `regie: false` — daar mag het nooit.
        regie=None if p.get("regie") is None else bool(p["regie"]),
        melder=gebeurtenis,
    )
    return {"gestart": True}


@methode("project.video")
def _project_video(p: dict[str, Any]) -> dict[str, Any] | None:
    from . import montage

    return montage.laatste_video(_vereist(p, "project"))


def verwerk(regel: str) -> dict[str, Any] | None:
    """Eén verzoekregel → één antwoord. Los te testen zonder pijpen."""
    regel = regel.strip()
    if not regel:
        return None
    try:
        verzoek = json.loads(regel)
    except json.JSONDecodeError as e:
        return {"id": None, "fout": {"bericht": f"geen geldige JSON: {e}", "soort": "Protocol"}}
    vid = verzoek.get("id")
    naam = verzoek.get("methode")
    fn = METHODES.get(naam)
    if fn is None:
        return {"id": vid, "fout": {"bericht": f"onbekende methode: {naam}", "soort": "Protocol"}}
    try:
        with contextlib.redirect_stdout(sys.stderr):
            return {"id": vid, "resultaat": fn(verzoek.get("params") or {})}
    except Exception as e:  # noqa: BLE001 — elke fout gaat als antwoord terug, de lus blijft leven
        traceback.print_exc(file=sys.stderr)
        return {"id": vid, "fout": {"bericht": str(e), "soort": type(e).__name__}}


def draai() -> None:
    global _uit
    # Het protocol is UTF-8 in beide richtingen. Op Windows staat een pijp
    # standaard op cp1252: zonder dit struikelt het inlezen van een verzoek
    # met een niet-ASCII projectnaam al voordat er een antwoord is.
    for stroom in (sys.stdin, sys.stdout):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stroom.reconfigure(encoding="utf-8")
    _uit = sys.stdout
    # Vanaf hier is stdout van het protocol en van niemand anders. Een print()
    # uit een werkdraad - buiten het `redirect_stdout` van `verwerk()` om -
    # zou er anders een regel tussen gooien die de app niet kan lezen.
    sys.stdout = sys.stderr
    for regel in sys.stdin:
        antwoord = verwerk(regel)
        if antwoord is not None:
            _schrijf(antwoord)
