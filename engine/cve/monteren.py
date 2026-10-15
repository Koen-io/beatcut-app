"""Monteren in stap 4 — volgorde, lengte, knippen, weghalen, en ongedaan maken.

Tot 13-10-2026 was Bijwerken bijsturen: welk stuk bron in een vak, hoe snel,
welk kader. De vakken zelf lagen vast. Dit bestand voegt toe wat een editor
een editor maakt, zonder de regel uit `bijwerken.py` te breken: **een snede
ligt op een tel.** Elke handeling hier verschuift snedes alleen van tel naar
tel; daarna zet `op_framerooster()` alles weer op hele frames.

  verplaats   een shot naar een andere plek. De vakken blijven staan (die
              komen uit de muziek); de inhoud schuift mee, zoals in een lijst.
  trim        de snede vóór of na een shot één of meer tellen opschuiven: het
              ene shot wordt langer, de buurman korter. Totale lengte gelijk.
  splits      een shot in tweeën op een tel binnenin; het tweede deel loopt
              de bron gewoon door.
  verwijder   een shot weg; de buurman (vorige, of volgende bij het eerste
              shot) neemt zijn vak over.

En de geschiedenis: elke wijziging in stap 4 bewaart eerst de vorige
`edl.json` in `geschiedenis/terug/`. Ongedaan maken zet die terug en bewaart
de huidige in `geschiedenis/vooruit/`; een nieuwe wijziging maakt vooruit
leeg. Vijftig stappen terug, daarna valt de oudste af. Bestanden, geen
geheugen: een herstart van de app kost je je undo niet.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import paths, projecten
from .edl import EDL, VideoBlok

GESCHIEDENIS = "geschiedenis"
MAX_STAPPEN = 50
# Een shot korter dan dit wordt niet gemaakt, ook niet als de tellen het
# toelaten: onder een kwart seconde lees je geen beeld meer, alleen een flits.
MIN_SHOT = 0.25
SNELHEID_MIN = 0.25


# -- geschiedenis ------------------------------------------------------------


def _map(pdir: Path, kant: str) -> Path:
    return pdir / GESCHIEDENIS / kant


def _stappen(map_: Path) -> list[Path]:
    if not map_.is_dir():
        return []
    return sorted(p for p in map_.glob("*.json") if p.stem.isdigit())


def _volgend(map_: Path) -> Path:
    bestaand = _stappen(map_)
    nr = int(bestaand[-1].stem) + 1 if bestaand else 1
    map_.mkdir(parents=True, exist_ok=True)
    return map_ / f"{nr:05d}.json"


def schrijf_met_stap(pdir: Path, edl: EDL) -> None:
    """Schrijf `edl` naar `edl.json` en zet de vorige montage op de terug-stapel.

    De enige manier waarop stap 4 `edl.json` hoort te schrijven. Volgorde is
    alles (Codex, 14-10-2026): eerst de oude montage bewaren, dán schrijven,
    en **pas als dat gelukt is** de vooruit-stapel leegmaken. Tot de
    reparatie gebeurde dat laatste vooraf, en een schrijffout (schijf vol,
    alleen-lezen) gooide de redo weg terwijl de montage zelf niet veranderde.
    Mislukt het schrijven, dan gaat ook de zojuist bewaarde stap weer weg.

    Een nieuwe wijziging maakt de vooruit-stapel leeg — wie na "ongedaan"
    iets anders doet, kiest een andere tak, net als in elke editor.
    """
    pad = pdir / "edl.json"
    stap: Path | None = None
    if pad.exists():
        stap = _volgend(_map(pdir, "terug"))
        shutil.copy2(pad, stap)
    try:
        edl.schrijf(pad)
    except BaseException:
        if stap is not None:
            stap.unlink(missing_ok=True)
        raise
    for p in _stappen(_map(pdir, "vooruit")):
        p.unlink(missing_ok=True)
    stappen = _stappen(_map(pdir, "terug"))
    for p in stappen[: max(0, len(stappen) - MAX_STAPPEN)]:
        p.unlink(missing_ok=True)


def bewaar_stap(pdir: Path) -> None:
    """Alleen de huidige montage op de terug-stapel; voor tests en de
    geschiedenisgrens. Wie schrijft gebruikt `schrijf_met_stap`."""
    edl = pdir / "edl.json"
    if not edl.exists():
        return
    shutil.copy2(edl, _volgend(_map(pdir, "terug")))
    stappen = _stappen(_map(pdir, "terug"))
    for p in stappen[: max(0, len(stappen) - MAX_STAPPEN)]:
        p.unlink(missing_ok=True)


def stand(project: str) -> dict:
    """Hoeveel stappen er terug en vooruit kunnen. Voor de knoppen in de app."""
    pdir = paths.PROJECTEN / project
    return {
        "terug": len(_stappen(_map(pdir, "terug"))),
        "vooruit": len(_stappen(_map(pdir, "vooruit"))),
    }


def _wissel_stapel(project: str, van: str, naar: str) -> dict:
    pdir = paths.project_dir(project)
    _niet_bezig(project)
    stapel = _stappen(_map(pdir, van))
    if not stapel:
        raise ValueError("Er is niets om " + ("ongedaan te maken." if van == "terug" else "opnieuw te doen."))
    bron = stapel[-1]
    # Eerst lezen: een kapot bestand op de stapel mag de montage niet slopen.
    vorige = EDL.van_dict(json.loads(bron.read_text(encoding="utf-8")))
    edlpad = pdir / "edl.json"
    tegenstap: Path | None = None
    if edlpad.exists():
        tegenstap = _volgend(_map(pdir, naar))
        shutil.copy2(edlpad, tegenstap)
    try:
        vorige.schrijf(edlpad)
    except BaseException:
        # Niets veranderd: dan ook niets op de andere stapel.
        if tegenstap is not None:
            tegenstap.unlink(missing_ok=True)
        raise
    bron.unlink()
    return _uit(project)


def ongedaan(project: str) -> dict:
    return _wissel_stapel(project, "terug", "vooruit")


def opnieuw(project: str) -> dict:
    return _wissel_stapel(project, "vooruit", "terug")


# -- hulp --------------------------------------------------------------------


def _niet_bezig(project: str) -> None:
    bezig = projecten.is_bezig(project)
    if bezig:
        # Een render leest edl.json in een werkdraad; daar mag niemand onder
        # schrijven.
        raise RuntimeError(f"Er loopt al werk aan dit project: {bezig}")


def _laad(project: str) -> tuple[Path, EDL]:
    pdir = paths.project_dir(project)
    _niet_bezig(project)
    pad = pdir / "edl.json"
    if not pad.exists():
        raise ValueError("Dit project heeft nog geen montage.")
    return pdir, EDL.lees(pad)


def _index(edl: EDL, shot: str) -> int:
    edl.sorteer()
    for i, b in enumerate(edl.video):
        if b.id == shot:
            return i
    raise ValueError(f"Shot {shot!r} staat niet in de montage.")


def _tellen(pdir: Path, edl: EDL) -> list[float]:
    """De tellen in tijdlijntijd, of een raster van halve seconden zonder muziek."""
    from .bijwerken import _lees, _raster

    analyse = _lees(pdir / "analysis.json") or {}
    offset = edl.audio[0].bron_start if edl.audio else 0.0
    tellen, _ = _raster(analyse, offset)
    if len(tellen) >= 2:
        return tellen
    n = int(edl.duur / 0.5) + 2
    return [round(i * 0.5, 4) for i in range(n)]


def _clipduren(pdir: Path) -> dict[str, float]:
    from .bijwerken import _lees

    ingest = _lees(pdir / "ingest.json") or {}
    return {c["id"]: float(c["duur"]) for c in ingest.get("clips") or []}


def _pas_in(blok: VideoBlok, clipduur: float | None) -> None:
    """Houd het venster binnen de clip; dezelfde regel als `bijwerken.zet_shot`.

    De tijdlijn is heilig, dus geeft de snelheid mee en dan het startpunt.
    """
    if clipduur is None or blok.duur <= 0:
        return
    # Een bevroren staart eet geen bron: alleen het bewegende deel telt. Met
    # de hele duur zou een stilstaand eindbeeld (`splits` in de staart) naar
    # een eerder moment teruggeklemd worden.
    beweegt = max(1e-3, blok.duur - blok.bevriezen)

    def nodig() -> float:
        return blok.bron_lengte if blok.snelheid_verloop else beweegt * blok.snelheid

    if nodig() > clipduur + 1e-6:
        if blok.snelheid_verloop:
            # Een ramp die niet meer past: vlak hem af tot wat er kan.
            blok.snelheid_verloop = []
        blok.snelheid = round(max(SNELHEID_MIN, min(blok.snelheid, clipduur / beweegt)), 3)
    ruimte = max(0.0, clipduur - nodig())
    blok.bron_start = round(max(0.0, min(blok.bron_start, ruimte)), 3)
    # Een overgang kan niet langer duren dan het shot waar hij in zit.
    if blok.overgang_in.duur > blok.duur * 0.5:
        blok.overgang_in.duur = round(blok.duur * 0.5, 3)
    blok.bevriezen = round(min(blok.bevriezen, max(0.0, blok.duur - 0.04)), 3)


def _schrijf(project: str, pdir: Path, edl: EDL) -> dict:
    duren = _clipduren(pdir)
    for b in edl.video:
        _pas_in(b, duren.get(b.clip))
    edl.op_framerooster()
    # Een ander stuk bron of een andere volgorde: de kleurafstemming opnieuw,
    # want het doel (de mediaan van de montage) en de bronmeting verschuiven.
    from .bijwerken import _lees
    from .kleurmatch import stem_af

    stem_af(edl, _lees(pdir / "analysis.json") or {})
    # Andere tijden: ondertitels en clipgeluid horen mee te schuiven, anders
    # staat de tekst onder het verkeerde beeld (review 14-10-2026). Snel: het
    # transcript per clip komt uit de cache.
    from .spraak import herleg

    herleg(edl, pdir, alleen_cache=True)
    schrijf_met_stap(pdir, edl)
    return _uit(project)


def _uit(project: str) -> dict:
    from .bijwerken import montage

    return montage(project)


def _nieuw_id(edl: EDL) -> str:
    bezet = {b.id for b in edl.video}
    n = len(edl.video) + 1
    while f"v{n:03d}" in bezet:
        n += 1
    return f"v{n:03d}"


# De inhoud van een vak: alles behalve waar en hoe lang het op de tijdlijn staat.
_INHOUD = ("clip", "bestand", "bron_start", "snelheid", "snelheid_verloop", "vulmodus",
           "kader", "zoom", "zoom_kracht", "geluid", "geluid_voor", "geluid_na",
           "reden", "bevriezen")


def _inhoud(b: VideoBlok) -> dict:
    import copy

    return {k: copy.deepcopy(getattr(b, k)) for k in _INHOUD}


# -- de vier handelingen -----------------------------------------------------


def verplaats(project: str, shot: str, naar: int) -> dict:
    """Zet de inhoud van `shot` op plek `naar` (0-gebaseerd); de rest schuift.

    De vakken (start, duur) blijven waar ze zijn — die komen uit de muziek.
    Een shot dat in een langer vak belandt laat meer van zijn bron zien; past
    dat niet, dan geeft de snelheid mee (`_pas_in`).
    """
    pdir, edl = _laad(project)
    van = _index(edl, shot)
    naar = max(0, min(int(naar), len(edl.video) - 1))
    if van == naar:
        return _uit(project)
    inhoud = [_inhoud(b) for b in edl.video]
    ids = [b.id for b in edl.video]
    inhoud.insert(naar, inhoud.pop(van))
    ids.insert(naar, ids.pop(van))
    for b, nieuw, bid in zip(edl.video, inhoud, ids, strict=True):
        for k, v in nieuw.items():
            setattr(b, k, v)
        b.id = bid
    # Wat verplaatst is, is handwerk.
    lo, hi = sorted((van, naar))
    for b in edl.video[lo : hi + 1]:
        b.vast = True
    _unieke_ids(edl)
    return _schrijf(project, pdir, edl)


def _unieke_ids(edl: EDL) -> None:
    gezien: set[str] = set()
    for b in edl.video:
        if b.id in gezien:
            b.id = _nieuw_id(edl)
        gezien.add(b.id)


def trim(project: str, shot: str, kant: str, tellen: int) -> dict:
    """Schuif de snede aan `kant` ("begin" of "eind") van dit shot `tellen` op.

    Positief is naar rechts. Eind +1: dit shot een tel langer, het volgende
    een tel korter. Begin −1: dit shot begint een tel eerder, het vorige
    eindigt een tel eerder. Het buurshot houdt het stuk bron dat aan de
    snede-kant van hem af ligt: wie aan zijn begin inlevert, begint later in
    de bron.
    """
    if kant not in ("begin", "eind"):
        raise ValueError("kant is 'begin' of 'eind'.")
    stap = int(tellen)
    if stap == 0:
        return _uit(project)
    pdir, edl = _laad(project)
    i = _index(edl, shot)
    links, rechts = (i - 1, i) if kant == "begin" else (i, i + 1)
    if links < 0 or rechts >= len(edl.video):
        raise ValueError("Aan die kant ligt geen ander shot; de eerste en laatste snede liggen vast.")
    a, b = edl.video[links], edl.video[rechts]
    raster = _tellen(pdir, edl)
    snede = b.tijdlijn_start
    huidig = min(range(len(raster)), key=lambda k: abs(raster[k] - snede))
    doel_k = huidig + stap
    if not 0 <= doel_k < len(raster):
        raise ValueError("Zo ver gaat de muziek niet.")
    nieuw = raster[doel_k]
    a_eind = b.tijdlijn_start + b.duur
    if nieuw - a.tijdlijn_start < MIN_SHOT or a_eind - nieuw < MIN_SHOT:
        raise ValueError("Dan wordt een van de twee shots korter dan een kwart seconde.")
    verschil = nieuw - snede
    a.duur = round(nieuw - a.tijdlijn_start, 6)
    # Het rechter shot verliest of wint aan zijn begin: zijn bron schuift mee,
    # zodat het einde van wat hij liet zien op dezelfde plek blijft.
    _verleg_begin(b, nieuw, a_eind - nieuw, verschil)
    a.vast = b.vast = True
    return _schrijf(project, pdir, edl)


def _verleg_begin(b: VideoBlok, start: float, duur: float, verschil: float) -> None:
    """Laat `b` op `start` beginnen met `duur`, met het einde van zijn bron vast.

    Bij constante snelheid schuift de bron `verschil × snelheid` mee. Bij een
    speed-ramp niet: de ramp is in fracties van de blokduur gegeven en rekt
    mee, dus dan rekenen we terug vanaf het oude bron-einde (Codex 14-10-2026:
    een ramp van 1× naar 3× verloor zo een halve seconde aan het einde).
    """
    if b.snelheid_verloop:
        oud_eind = b.bron_start + b.bron_lengte
        b.tijdlijn_start = round(start, 6)
        b.duur = round(duur, 6)
        b.bron_start = round(max(0.0, oud_eind - b.bron_lengte), 3)
        return
    b.bron_start = round(max(0.0, b.bron_start + verschil * b.snelheid), 3)
    b.tijdlijn_start = round(start, 6)
    b.duur = round(duur, 6)


def splits(project: str, shot: str, op: float | None = None) -> dict:
    """Knip een shot in tweeën op de tel die het dichtst bij `op` ligt.

    `op` in tijdlijnseconden; zonder `op` de middelste tel van het shot. Het
    tweede deel loopt de bron door, met dezelfde snelheid en een harde snede
    ertussen — er is niets te overgangen binnen één doorlopend beeld.
    """
    pdir, edl = _laad(project)
    i = _index(edl, shot)
    blok = edl.video[i]
    begin, eind = blok.tijdlijn_start, blok.tijdlijn_start + blok.duur
    raster = [t for t in _tellen(pdir, edl) if begin + MIN_SHOT <= t <= eind - MIN_SHOT]
    if not raster:
        raise ValueError("Dit shot is te kort om te knippen: er ligt geen tel binnenin.")
    doel = (begin + eind) / 2.0 if op is None else float(op)
    knip = min(raster, key=lambda t: abs(t - doel))

    import copy

    tweede = copy.deepcopy(blok)
    tweede.id = _nieuw_id(edl)
    eerste_duur = knip - begin
    # Een ramp loopt over het hele shot; doorgeknipt wordt hij twee halve
    # ramps die niet meer kloppen. Dan liever de gemiddelde snelheid.
    if blok.snelheid_verloop:
        gem = blok.bron_lengte / blok.duur if blok.duur > 0 else 1.0
        for b in (blok, tweede):
            b.snelheid_verloop = []
            b.snelheid = round(gem, 3)
    # Een blok beweegt `duur − bevriezen` seconden en houdt dan zijn laatste
    # beeld vast. Waar de knip valt bepaalt wat elk deel laat zien (Codex
    # 14-10-2026: een knip in de bevroren staart liet beide delen ander beeld
    # zien dan het origineel).
    beweegt = max(0.0, blok.duur - blok.bevriezen)
    tweede.tijdlijn_start = round(knip, 6)
    tweede.duur = round(eind - knip, 6)
    if eerste_duur <= beweegt + 1e-6:
        # Knip in het bewegende deel: het eerste deel beweegt tot de knip, het
        # tweede loopt de bron door en houdt de staart van het origineel.
        blok.duur = round(eerste_duur, 6)
        blok.bevriezen = 0.0
        tweede.bron_start = round(blok.bron_start + eerste_duur * blok.snelheid, 3)
    else:
        # Knip in de staart: het eerste deel houdt zijn beweging en een kortere
        # staart; het tweede is het stilstaande eindbeeld. Eén bewegend frame
        # (de renderer wil er minstens één) op het laatste bronframe, de rest stil.
        frame = 1.0 / max(1, edl.canvas.fps)
        laatste = blok.bron_start + beweegt * blok.snelheid
        blok.duur = round(eerste_duur, 6)
        blok.bevriezen = round(eerste_duur - beweegt, 6)
        tweede.bron_start = round(max(0.0, laatste - frame), 3)
        tweede.snelheid = 1.0
        tweede.bevriezen = round(max(0.0, tweede.duur - frame), 6)
    tweede.overgang_in = type(blok.overgang_in)()  # snede
    blok.vast = tweede.vast = True
    edl.video.insert(i + 1, tweede)
    return _schrijf(project, pdir, edl)


def verwijder(project: str, shot: str) -> dict:
    """Haal een shot weg; het vorige shot (of het volgende) neemt zijn vak over."""
    pdir, edl = _laad(project)
    if len(edl.video) < 2:
        raise ValueError("Een montage zonder shots kan niet; dit is het laatste.")
    i = _index(edl, shot)
    weg = edl.video.pop(i)
    if i > 0:
        buur = edl.video[i - 1]
        buur.duur = round(weg.tijdlijn_start + weg.duur - buur.tijdlijn_start, 6)
    else:
        buur = edl.video[0]
        eind = buur.tijdlijn_start + buur.duur
        # Het volgende shot schuift naar voren en begint eerder in zijn bron.
        _verleg_begin(
            buur, weg.tijdlijn_start, eind - weg.tijdlijn_start,
            weg.tijdlijn_start - buur.tijdlijn_start,
        )
        buur.overgang_in = weg.overgang_in
    buur.vast = True
    return _schrijf(project, pdir, edl)
