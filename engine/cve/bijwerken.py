"""Stap 4 — Bijwerken: de montage zien en bijsturen zonder alles over te doen.

Alles hier leest en schrijft `edl.json` (regel 3). Eén ding is daarbij
heilig: **de tijdlijnpositie van een shot komt uit de muziek, niet uit de
gebruiker.** Wie een shot bijwerkt verandert alleen *wat er in dat vak te
zien is* — welk stuk bron, hoe snel. `start`, `duur` en `frames` blijven
staan. Vandaar dat `zet_shot()` nergens `pak_aan()` aanroept: dat schuift de
blokken tegen elkaar aan en dan is de beat-sync weg (zie `edl.pak_aan`).

Wat de gebruiker over een clip zegt — "moet erin", "nooit gebruiken" — is een
voorkeur, geen montage. Die staat dus in `projecten/<naam>/voorkeuren.json`
naast `selectie.json` en niet in de EDL; een EDL zonder blokken is ongeldig,
dus vóór de eerste montage is daar geen plek voor. Net als bij `clip.zet` is
de sleutel de **bestandsnaam**, want clip-id's worden bij een nieuwe ingest
opnieuw uitgedeeld.

Elke voorkeur gaat ook naar het stijl-geheugen (`geheugen.noteer`), precies
zoals de oude Studio het deed: "nooit" is een verwijderd shot, "moet erin"
een vastgezet shot.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import looks, media, paths, projecten
from .edl import EDL, VideoBlok

VOORKEUREN = "voorkeuren.json"
# Breedte van een shotbeeldje in de tijdlijn. Klein: er staan er tientallen
# naast elkaar en elk beeldje is een ffmpeg-aanroep.
SHOT_BREEDTE = 192
# Zoveel waarden gaan er van de golfvorm over de draad. De cache van de
# Studio heeft er 1800; meer dan dit kan geen enkel spoor laten zien.
GOLF_PUNTEN = 400
SNELHEID_MIN = 0.25
SNELHEID_MAX = 2.0


# -- lezen -----------------------------------------------------------------


def _lees(pad: Path) -> dict | None:
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def voorkeuren(project: str) -> dict:
    """Wat de gebruiker over losse clips gezegd heeft, op bestandsnaam."""
    d = _lees(paths.PROJECTEN / project / VOORKEUREN) or {}
    return {
        "moet": sorted(set(d.get("moet") or [])),
        "nooit": sorted(set(d.get("nooit") or [])),
    }


def zet_voorkeur(project: str, clip: str, soort: str | None) -> dict:
    """Zet "moet"/"nooit" op een clip, of haal de voorkeur weg (`None`).

    Moet en nooit sluiten elkaar uit — ze staan in het ontwerp ook als twee
    knoppen naast elkaar, niet als twee vinkjes.
    """
    if soort not in ("moet", "nooit", None, ""):
        raise ValueError(f"onbekende voorkeur: {soort!r}")
    huidig = voorkeuren(project)
    for sleutel in ("moet", "nooit"):
        huidig[sleutel] = [c for c in huidig[sleutel] if c != clip]
    if soort:
        huidig[soort] = sorted({*huidig[soort], clip})

    pad = paths.project_dir(project) / VOORKEUREN
    deel = pad.with_name(pad.name + ".deel")
    deel.write_text(
        json.dumps({"versie": 1, **huidig}, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    deel.replace(pad)
    return huidig


def _clip_ids(project: str) -> dict[str, str]:
    """Bestandsnaam → clip-id, uit `ingest.json`."""
    ing = _lees(paths.PROJECTEN / project / "ingest.json") or {}
    return {c["bestand"]: c["id"] for c in ing.get("clips") or []}


def _naar_ids(project: str, bestanden: list[str]) -> list[str]:
    op_naam = _clip_ids(project)
    return [op_naam[b] for b in bestanden if b in op_naam]


# -- het tel-raster --------------------------------------------------------


def _raster(analyse: dict, offset: float) -> tuple[list[float], list[dict]]:
    """Tellen en maten in tijdlijntijd: de muziektijd min waar de montage begint.

    `offset` is `audio[0].bron_start` uit de EDL — daar begint de track, en
    daarmee valt tel 0 van het raster op seconde 0 van de montage.
    """
    muziek = analyse.get("muziek") or {}
    beats = [round(b - offset, 4) for b in muziek.get("beats") or [] if b >= offset - 1e-6]
    # `maten` is een deelverzameling van `beats` met dezelfde afronding
    # (`analyze/muziek.py`), dus vergelijken op waarde mag hier.
    maat_tijden = {round(m - offset, 4) for m in muziek.get("maten") or [] if m >= offset - 1e-6}
    maten = []
    for i, t in enumerate(beats):
        if t in maat_tijden:
            maten.append({"tel": i, "t": t, "nummer": len(maten) + 1})
    return beats, maten


def _dichtste_tel(tellen: list[float], t: float) -> int | None:
    if not tellen:
        return None
    return min(range(len(tellen)), key=lambda i: abs(tellen[i] - t))


# -- beeldjes en golfvorm --------------------------------------------------


def _shotbeeldje(pdir: Path, clip_id: str, proxy: Path, op: float) -> str | None:
    """Eén beeldje uit de proxy op het moment dat dit shot laat zien.

    De cachenaam bevat het moment in milliseconden, dus een shot dat opschuift
    krijgt een nieuw beeldje en een shot dat terugschuift het oude terug.
    """
    if not proxy.exists():
        return None
    doel = pdir / "cache" / "shots" / f"{clip_id}-{int(round(op * 1000)):08d}.jpg"
    try:
        media.maak_thumbnail(proxy, doel, breedte=SHOT_BREEDTE, op=op)
    except Exception:  # noqa: BLE001 — één leeg beeldje mag de tijdlijn niet slopen
        return None
    return str(doel)


def _golfvorm(project: str) -> list[float]:
    """De amplitude van de muziek, teruggebracht tot `GOLF_PUNTEN` waarden.

    Hergebruikt de cache van de Studio. Die cache is níet op de track
    gesleuteld, dus hij gaat eerst weg als de muziek nieuwer is dan de cache —
    anders zie je de golfvorm van de vorige track onder je montage.
    """
    from .studio import maak_golfvorm

    pdir = paths.PROJECTEN / project
    cache = pdir / "cache" / "golfvorm.json"
    sporen = media.vind_muziek(pdir / "muziek")
    if not sporen:
        return []
    if cache.exists() and cache.stat().st_mtime < sporen[0].stat().st_mtime:
        cache.unlink()
    if maak_golfvorm(project, log=lambda *_: None) is None:
        return []

    punten = (_lees(cache) or {}).get("punten") or []
    if len(punten) <= GOLF_PUNTEN:
        return punten
    blok = len(punten) / GOLF_PUNTEN
    return [
        round(max(punten[int(i * blok) : max(int(i * blok) + 1, int((i + 1) * blok))]), 3)
        for i in range(GOLF_PUNTEN)
    ]


# -- de montage ------------------------------------------------------------


def _signalen(analyse: dict, blok: VideoBlok) -> tuple[dict[str, float], float | None]:
    """De gemeten signalen van het segment waar dit shot uit komt, plus score.

    Dit is "Waarom dit shot" uit het ontwerp: niet een mening maar de
    onderdelen die de regisseur ook gebruikte.
    """
    from .geheugen import _segment_bij

    seg = _segment_bij(analyse, blok.clip, blok.bron_start, blok.duur)
    if not seg:
        return {}, None
    onderdelen = {k: round(float(v), 3) for k, v in (seg.get("onderdelen") or {}).items()}
    return onderdelen, round(float(seg.get("score", 0.0)), 3)


def _clipblok(pdir: Path, analyse: dict, clip_id: str, ingest: dict) -> dict:
    """Wat de inspecteur van een clip moet weten: filmstrip en scorelijn."""
    rij = next((c for c in ingest.get("clips") or [] if c["id"] == clip_id), None)
    duur = float(rij["duur"]) if rij else 0.0
    strip = pdir / "cache" / "thumbs" / f"{clip_id}.jpg"
    punten = [
        {"t": round((s["start"] + s["eind"]) / 2.0, 3), "waarde": round(float(s.get("score", 0)), 3)}
        for s in analyse.get("segmenten") or []
        if s.get("clip") == clip_id
    ]
    return {
        "id": clip_id,
        "bestand": rij["bestand"] if rij else "",
        "duur": duur,
        "proxy": str(pdir / "proxies" / rij["proxy"]) if rij else None,
        "strip": str(strip) if strip.exists() else None,
        "strip_frames": 24,  # studio.THUMBS_PER_CLIP
        "score": sorted(punten, key=lambda p: p["t"]),
    }


def _muziekpad(pdir: Path, bestand: str | None) -> str | None:
    """Het muziekbestand van het project, als absoluut pad."""
    if not bestand:
        return None
    pad = pdir / "muziek" / bestand
    return str(pad) if pad.exists() else None


def montage(project: str) -> dict | None:
    """De montage zoals hij nu in `edl.json` staat, klaar om te tekenen.

    `None` als er nog geen montage is. Dat is geen fout: stap 4 is dan simpel
    leeg en stuurt de gebruiker terug naar Stijl.
    """
    pdir = paths.PROJECTEN / project
    edlpad = pdir / "edl.json"
    if not edlpad.exists():
        return None
    edl = EDL.lees(edlpad)
    analyse = _lees(pdir / "analysis.json") or {}
    ingest = _lees(pdir / "ingest.json") or {}
    muziek = analyse.get("muziek") or {}

    offset = edl.audio[0].bron_start if edl.audio else 0.0
    tellen, maten = _raster(analyse, offset)
    # Het raster loopt over de hele track; de tijdlijn toont alleen de montage.
    # Anders stond er "424 tellen · 106 maten" onder een video van 31 s.
    tellen = [t for t in tellen if t <= edl.duur + 1e-3]
    maten = [m for m in maten if m["t"] <= edl.duur + 1e-3]

    # De filmstrips van de Studio: één ffmpeg per clip voor 24 beeldjes, en
    # daarna uit de cache. Hergebruikt, want dit is precies waarvoor hij
    # gemaakt is — zie `studio.maak_thumbnails`.
    if ingest.get("clips"):
        from .studio import maak_thumbnails

        maak_thumbnails(project, log=lambda *_: None)

    voork = voorkeuren(project)
    op_id = {c["id"]: c for c in ingest.get("clips") or []}

    shots = []
    for nr, b in enumerate(edl.video, start=1):
        tel = _dichtste_tel(tellen, b.tijdlijn_start)
        eind_tel = _dichtste_tel(tellen, b.tijdlijn_start + b.duur)
        onderdelen, score = _signalen(analyse, b)
        rij = op_id.get(b.clip)
        proxy = pdir / "proxies" / rij["proxy"] if rij else pdir / "proxies" / b.bestand
        shots.append(
            {
                "id": b.id,
                "nr": nr,
                "clip": b.clip,
                "bestand": b.bestand,
                "start": b.tijdlijn_start,
                "duur": b.duur,
                "frames": b.frames,
                "tel": tel,
                "tel_afwijking": None if tel is None else round(b.tijdlijn_start - tellen[tel], 4),
                "tellen": max(1, (eind_tel - tel) if tel is not None and eind_tel is not None else 1),
                "bron_in": b.bron_start,
                "bron_duur": round(b.bron_lengte, 3),
                "ramp": bool(b.snelheid_verloop),
                "snelheid": b.snelheid,
                # De speed-ramp als dezelfde (uitvoerduur, snelheid)-stukken
                # waar de renderer mee rekent. Zonder deze lijst speelt de
                # voorvertoning een ramp-shot op constante snelheid en ligt het
                # midden van het shot naast de beat. Zie VideoBlok.snelheid_stukken.
                "snelheid_stukken": [
                    [round(d, 5), round(v, 5)] for d, v in b.snelheid_stukken()
                ],
                "overgang": b.overgang_in.soort,
                # De speler heeft de duur nodig om te weten hoe lang hij twee
                # beelden naast elkaar moet houden; zonder duur is elke
                # overgang een snede. Zie app/src/speler/Speler.tsx.
                "overgang_duur": b.overgang_in.duur,
                "zoom": b.zoom,
                "zoom_kracht": b.zoom_kracht,
                "bevriezen": b.bevriezen,
                "vulmodus": b.vulmodus,
                "proxy": str(proxy) if proxy.exists() else None,
                "reden": b.reden,
                "vast": b.vast,
                "score": score,
                "signalen": onderdelen,
                "moet": b.bestand in voork["moet"],
                "nooit": b.bestand in voork["nooit"],
                "thumbnail": _shotbeeldje(pdir, b.clip, proxy, b.bron_start),
            }
        )

    return {
        "project": project,
        "stijl": edl.stijl,
        "montage": edl.brief.get("montage") or "",
        "vorm": f"{edl.canvas.breedte}:{edl.canvas.hoogte}",
        "fps": edl.canvas.fps,
        "duur": edl.duur,
        "bpm": muziek.get("bpm"),
        "muziek": {
            "bestand": muziek.get("bestand"),
            "bron_start": offset,
            # Absoluut pad, want de speler laadt het bestand zelf: de muziek is
            # daar de meesterklok en het beeld volgt.
            "pad": _muziekpad(pdir, muziek.get("bestand")),
        },
        "look": {"id": edl.look.id, "sterkte": edl.look.sterkte},
        "afwerking": asdict(edl.afwerking),
        "effectseed": edl.effectseed,
        "tellen": tellen,
        "maten": maten,
        "golfvorm": _golfvorm(project),
        "shots": shots,
        "titels": [
            {
                "id": o.id,
                "soort": o.soort,
                "start": o.tijdlijn_start,
                "duur": o.duur,
                "tekst": str(o.inhoud.get("titel") or o.inhoud.get("tekst") or ""),
            }
            for o in edl.overlay
        ],
        "clips": {
            cid: _clipblok(pdir, analyse, cid, ingest)
            for cid in dict.fromkeys(b.clip for b in edl.video)
        },
        "voorkeuren": voork,
    }


# -- één shot bijwerken ----------------------------------------------------


def zet_shot(
    project: str, shot: str, *, snelheid: float | None = None, bron_in: float | None = None
) -> dict:
    """Pas één shot aan zonder de tijdlijn te verschuiven.

    Geeft de hele montage terug, want een shot verandert ook de scorelijn en
    het beeldje; twee bronnen van waarheid in de interface is er één te veel.
    """
    pdir = paths.PROJECTEN / project
    edlpad = pdir / "edl.json"
    if not edlpad.exists():
        raise ValueError("Dit project heeft nog geen montage.")
    edl = EDL.lees(edlpad)
    blok = next((b for b in edl.video if b.id == shot), None)
    if blok is None:
        raise ValueError(f"Shot {shot!r} staat niet in de montage.")

    if snelheid is not None:
        blok.snelheid = max(SNELHEID_MIN, min(SNELHEID_MAX, float(snelheid)))
        # Een zelf gekozen snelheid is een vaste snelheid: de ramp van de
        # montagestijl gaat eraf, anders wint die stilletjes.
        blok.snelheid_verloop = []
    if bron_in is not None:
        blok.bron_start = max(0.0, round(float(bron_in), 3))

    # Het venster moet binnen de clip blijven: het shot duurt `duur`
    # tijdlijnseconden en eet daarvoor `duur * snelheid` seconden bron op.
    # Eerst de snelheid, dan het startpunt. Alleen het startpunt begrenzen was
    # niet genoeg: een shot van 4 s op 2x vraagt 8 s uit een clip van 5, en
    # ffmpeg leverde toen 75 van de gevraagde 120 frames — waarna alles erna
    # van de beat schoof. De tijdlijn is heilig (zie de kop van dit bestand),
    # dus de snelheid geeft mee in plaats van de duur.
    ingest = _lees(pdir / "ingest.json") or {}
    rij = next((c for c in ingest.get("clips") or [] if c["id"] == blok.clip), None)
    if rij:
        clipduur = float(rij["duur"])
        if blok.duur > 0:
            haalbaar = max(SNELHEID_MIN, clipduur / blok.duur)
            blok.snelheid = round(min(blok.snelheid, haalbaar), 3)
        ruimte = clipduur - blok.bron_lengte
        blok.bron_start = round(max(0.0, min(blok.bron_start, ruimte)), 3)

    # Geen `pak_aan()`, geen `op_framerooster()`: de tijden komen uit de
    # muziek en blijven exact zoals ze stonden.
    edl.schrijf(edlpad)
    return montage(project)


# -- opnieuw regisseren ----------------------------------------------------


def regisseer(
    project: str,
    *,
    stijl: str | None = None,
    # Niet `montage`: dat is hierboven de functie die de tijdlijn teruggeeft.
    montagestijl: str | None = None,
    vorm: str | None = None,
    duur: float | None = None,
) -> dict:
    """Alleen de regie opnieuw: nieuwe shotkeuze, geen render.

    Respecteert wat de gebruiker zei: clips op "nooit" komen er niet in, clips
    op "moet" krijgen voorrang bij de keuze. Duurt tienden van seconden, want
    er komt geen ffmpeg aan te pas — alleen de beeldjes van de nieuwe shots.
    """
    from .director import Brief, kies_regisseur

    pdir = paths.project_dir(project)
    analyse = _lees(pdir / "analysis.json")
    if analyse is None:
        raise ValueError("Dit project is nog niet geanalyseerd.")

    bestaand = EDL.lees(pdir / "edl.json") if (pdir / "edl.json").exists() else None
    if stijl is None:
        stijl = bestaand.stijl if bestaand else analyse.get("stijl", "actie")
    if montagestijl is None:
        # De montagestijl staat in de brief van de vorige montage; die is de
        # enige plek waar hij bewaard wordt (zie `montage.brief_van`).
        montagestijl = str((bestaand.brief.get("montage") if bestaand else "") or "")
    if vorm is None:
        vorm = (
            f"{bestaand.canvas.breedte}:{bestaand.canvas.hoogte}" if bestaand else "16:9"
        )
        vorm = {"1920:1080": "16:9", "1080:1920": "9:16", "1080:1080": "1:1"}.get(vorm, "16:9")

    voork = voorkeuren(project)
    if not projecten.neem_bezig(project, "De montage opnieuw bedenken…"):
        raise RuntimeError(f"Er loopt al werk aan dit project: {projecten.is_bezig(project)}")
    try:
        voorstel = kies_regisseur("preset").stel_voor(
            analyse,
            Brief(
                doelduur=duur,
                stijl=stijl,
                montage=montagestijl,
                vorm=vorm,
                uitgesloten=sorted(
                    {*_naar_ids(project, voork["nooit"]), *_uitgesloten_ids(project)}
                ),
                voorkeur=_naar_ids(project, voork["moet"]),
            ),
        )
        if not voorstel.edl.video:
            raise ValueError(
                " ".join(voorstel.waarschuwingen)
                or "Te weinig bruikbaar materiaal voor een montage."
            )
        looks.pas_toe(voorstel.edl, looks.keuze(project))
        # De brief hoort mee: na "opnieuw regisseren" is dít de montage die bij
        # de huidige keuze hoort, en mag "Exporteer op volle kwaliteit" hem
        # niet nog eens overdoen. Zie `montage.regie_nodig()`.
        from . import montage as montage_mod

        voorstel.edl.brief = montage_mod.brief_van(stijl, vorm, duur, montagestijl)
        voorstel.edl.schrijf(pdir / "edl.json")
    finally:
        projecten.zet_bezig(project, None)

    gebruikt = {b.bestand for b in voorstel.edl.video}
    waarschuwingen = list(voorstel.waarschuwingen)
    for naam in voork["moet"]:
        if naam not in gebruikt:
            waarschuwingen.append(
                f"{naam} past nergens in dit ritme — geen enkel stuk is lang genoeg."
            )

    return {
        "montage": montage(project),
        "uitleg": voorstel.uitleg,
        "waarschuwingen": waarschuwingen,
    }


def _uitgesloten_ids(project: str) -> list[str]:
    """De clips die in stap 1 zijn uitgezet, als clip-id."""
    from . import montage as montage_mod

    return montage_mod._uitgesloten(project)


# -- het stijl-geheugen ----------------------------------------------------


def _shotverwijzing(project: str, clip_id: str) -> dict | None:
    """Een `{clip, bron_start, duur}` om een voorkeur aan te hangen.

    Eerst het shot dat nu in de montage staat — dat is wat de gebruiker ziet
    als hij op de knop drukt. Staat de clip er niet in (dat is juist bij
    "moet erin" waarschijnlijk), dan het beste segment van die clip.
    """
    pdir = paths.PROJECTEN / project
    edl = _lees(pdir / "edl.json") or {}
    for b in edl.get("video") or []:
        if b.get("clip") == clip_id:
            return {"clip": clip_id, "bron_start": b["bron_start"], "duur": b["duur"]}
    analyse = _lees(pdir / "analysis.json") or {}
    van_clip = [s for s in analyse.get("segmenten") or [] if s.get("clip") == clip_id]
    if not van_clip:
        return None
    beste = max(van_clip, key=lambda s: s.get("score", 0.0))
    return {
        "clip": clip_id,
        "bron_start": beste["start"],
        "duur": round(beste["eind"] - beste["start"], 3),
    }


def voorkeur(project: str, clip: str, soort: str | None) -> dict:
    """Bewaar de voorkeur en laat het stijl-geheugen ervan leren.

    Mislukt het leren, dan gaat de voorkeur wél door: de gebruiker was aan het
    monteren, niet aan het trainen. Dezelfde afweging als in de oude Studio.
    """
    stand = zet_voorkeur(project, clip, soort)
    geleerd = None
    fout = None
    if soort in ("moet", "nooit"):
        from .geheugen import noteer

        clip_id = _clip_ids(project).get(clip)
        verwijzing = _shotverwijzing(project, clip_id) if clip_id else None
        if verwijzing:
            edlpad = paths.PROJECTEN / project / "edl.json"
            stijl = EDL.lees(edlpad).stijl if edlpad.exists() else "actie"
            try:
                geleerd = noteer(
                    project,
                    "verwijderd" if soort == "nooit" else "vastgezet",
                    stijl=stijl,
                    weg=verwijzing if soort == "nooit" else None,
                    houd=verwijzing if soort == "moet" else None,
                )
            except Exception as e:  # noqa: BLE001 — leren mag de keuze niet blokkeren
                fout = str(e)
    return {"clip": clip, "soort": soort or None, **stand, "geleerd": geleerd, "fout": fout}
