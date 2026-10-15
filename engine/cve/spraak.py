"""Spraak in de BeatCut 2-route: ondertitels, eigen geluid en ducking.

Alles eronder bestond al voor de oude Studio: `transcript.py` (whisper.cpp,
lokaal, per clip gecachet), het sjabloon `brands/sjablonen/ondertitels.html`
en in `render.py` het ducken van de muziek waar gepraat wordt plus de J/L-cuts
van het clipgeluid. Wat ontbrak tot 13-10-2026 was de koppeling: geen
RPC-methode riep het aan, en de regisseur zette nooit `geluid` op een blok —
dus de ducking had niets om voor te ducken.

Dit bestand is die koppeling:

  stand      aan/uit, hoeveel woorden, instellingen (`spraak.json`)
  maak       transcript → `ondertitels.json` → overlay in de EDL → eigen
             geluid aan op elk shot waarin gepraat wordt, met een J/L-cut
  weg        alles weer uit
  herleg     na een nieuwe regie (andere shots, andere tijden) de overlay en
             het clipgeluid opnieuw op de montage leggen. Snel: het transcript
             per clip komt uit de cache.

Spraak staat per project in `spraak.json`; de regisseur kijkt daar niet naar,
`herleg()` wel. Zo overleeft de keuze "ondertitels aan" elke hermontage.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from . import paths, projecten
from .edl import EDL

SPRAAK = "spraak.json"
# Hoe ver het eigen geluid vóór en na het beeld doorloopt (J- en L-cut).
# Een derde seconde is wat een luisteraar als "natuurlijk" hoort zonder dat
# het volgende shot al hoorbaar is voor het in beeld komt.
J_CUT = 0.3
L_CUT = 0.3
# Sterkte van het clipgeluid onder de muziek. 1,0 is vol; de muziek wordt
# daar tegelijk geduckt (`render._duck_uitdrukking`).
GELUID = 1.0

STANDAARD = {
    "aan": False,
    "kleur": "#ffffff",
    "grootte": "normaal",
    "positie": "onder",
    "stijl": "karaoke",
    "taal": "auto",
}


def _pad(project: str) -> Path:
    return paths.PROJECTEN / project / SPRAAK


def instellingen(project: str) -> dict:
    try:
        d = json.loads(_pad(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(STANDAARD)
    return {**STANDAARD, **{k: v for k, v in d.items() if k in STANDAARD}}


def _schrijf_instellingen(project: str, d: dict) -> None:
    _pad(project).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def stand(project: str) -> dict:
    """Voor de app: staat spraak aan, en wat is er gevonden?"""
    inst = instellingen(project)
    pdir = paths.PROJECTEN / project
    woorden = regels = 0
    # Uit de ondertitel-laag in edl.json: die gaat mee met ongedaan maken,
    # `ondertitels.json` niet (review 15-10-2026).
    try:
        edl = EDL.lees(pdir / "edl.json")
        laag = next((o for o in edl.overlay if o.soort == "ondertitels"), None)
        if laag is not None:
            lijst = json.loads(laag.inhoud.get("regels") or "[]")
            regels = len(lijst)
            woorden = sum(len(r.get("woorden") or []) for r in lijst)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    from . import spraakinstall

    heeft_bin = paths.whisper_bin() is not None
    heeft_model = paths.whisper_model() is not None
    return {
        **inst,
        "woorden": woorden,
        "regels": regels,
        "kan": heeft_bin and heeft_model,
        # Ontbreekt alleen het model, dan kan de app het ophalen
        # (spraakinstall.py, 15-10-2026). Ontbreekt de binary, dan niet.
        "model_ophaalbaar": heeft_bin and not heeft_model,
        "model_bytes": spraakinstall.GROOTTE,
        "installeren_bezig": spraakinstall.is_bezig(),
    }


# -- op de montage leggen ----------------------------------------------------


def _leg_op(edl: EDL, pdir: Path, inst: dict, *, log=print) -> dict:
    """Transcript op deze EDL, overlay erin, eigen geluid aan. Schrijft niets."""
    from . import transcript
    from .graphics import ondertitel_overlay

    taal = str(inst.get("taal") or "auto")
    woorden = transcript.op_tijdlijn(edl, pdir, taal=taal, log=log)
    regels = transcript.groepeer(woorden)
    data = {
        "versie": 1,
        "aantal_woorden": len(woorden),
        "regels": [asdict(r) for r in regels],
    }
    (pdir / "ondertitels.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    edl.overlay = [o for o in edl.overlay if o.soort != "ondertitels"]
    if regels:
        blok = ondertitel_overlay(data["regels"], edl)
        blok.inhoud.update(
            {k: inst[k] for k in ("kleur", "grootte", "positie", "stijl")}
        )
        edl.overlay.append(blok)

    # Eigen geluid aan waar gepraat wordt. Zonder dit is de ondertitel een
    # tekst bij een stem die je niet hoort, en de ducking duckt voor niets.
    for b in edl.video:
        a, z = b.tijdlijn_start, b.tijdlijn_start + b.duur
        praat = any(w.start < z and w.eind > a for w in woorden)
        if praat:
            b.geluid = GELUID
            b.geluid_voor = round(min(J_CUT, b.bron_start), 3)
            b.geluid_na = L_CUT
        elif b.geluid == GELUID and b.reden.endswith("· spraak"):
            # Eerder door ons aangezet, nu geen spraak meer in dit vak.
            b.geluid = b.geluid_voor = b.geluid_na = 0.0
        if praat and not b.reden.endswith("· spraak"):
            b.reden = f"{b.reden} · spraak".strip(" ·")
    return data


def herleg(edl: EDL, pdir: Path, *, log=lambda *_: None, alleen_cache: bool = False) -> None:
    """Na een nieuwe regie: ondertitels en clipgeluid opnieuw op de montage.

    Doet niets als spraak voor dit project niet aanstaat. Wordt aangeroepen
    met een EDL die nog niet geschreven is; de aanroeper schrijft.

    `alleen_cache`: voor de knoppen in stap 4 (trimmen, verplaatsen, …). Die
    draaien in de RPC-lus, en daar mag whisper nooit tientallen seconden gaan
    rekenen (review 15-10-2026). Ontbreekt er voor een clip een transcript,
    dan blijft de laag zoals hij was; de volgende regie of "ondertitels aan"
    legt hem goed.
    """
    inst = instellingen(pdir.name)
    if not inst["aan"]:
        return
    if alleen_cache:
        from . import transcript

        taal = str(inst.get("taal") or "auto")
        bronnen = {b.bestand for b in edl.video}
        ontbreekt = [
            n for n in bronnen
            if (pdir / "bronnen" / n).exists()
            and not transcript.heeft_cache(pdir / "bronnen" / n, pdir / "cache", taal=taal)
        ]
        if ontbreekt:
            log(f"spraak niet opnieuw gelegd: geen transcript voor {', '.join(sorted(ontbreekt))}")
            return
    try:
        _leg_op(edl, pdir, inst, log=log)
    except Exception as e:  # noqa: BLE001 — een montage zonder ondertitels is beter dan geen montage
        log(f"spraak niet opnieuw gelegd: {e}")


def maak(project: str, *, instellingen_nieuw: dict | None = None, melder=None) -> threading.Thread:
    """Spraak aanzetten: transcriberen (whisper), overlay en geluid in de EDL.

    In een werkdraad, met `voortgang`/`klaar`/`fout` naar `melder`, net als
    `projecten.verwerk`. Transcriberen van 21 clips kost op de M4 Pro ~40 s
    de eerste keer; daarna komt alles uit `cache/transcript/`.
    """
    pdir = paths.project_dir(project)
    if not (pdir / "edl.json").exists():
        raise ValueError("Dit project heeft nog geen montage.")
    if paths.whisper_bin() is None or paths.whisper_model() is None:
        raise RuntimeError("whisper.cpp of het model ontbreekt; `cve doctor` toont wat er mist.")
    inst = {**instellingen(project), **(instellingen_nieuw or {}), "aan": True}
    if not projecten.neem_bezig(project, "Spraak herkennen…"):
        raise RuntimeError(f"Er loopt al werk aan dit project: {projecten.is_bezig(project)}")

    def meld(soort: str, data: dict) -> None:
        if melder is not None:
            melder(soort, {"werk": "spraak", "project": project, **data})

    def werk() -> None:
        try:
            def log(t) -> None:
                projecten.zet_bezig(project, f"Spraak — {t}")
                meld("voortgang", {"stap": "spraak", "tekst": str(t), "gedaan": 0, "totaal": 0})

            edl = EDL.lees(pdir / "edl.json")
            data = _leg_op(edl, pdir, inst, log=log)
            _schrijf_instellingen(project, inst)
            from .monteren import schrijf_met_stap

            schrijf_met_stap(pdir, edl)
        except Exception as e:  # noqa: BLE001
            projecten.zet_bezig(project, None)
            meld("fout", {"fout": str(e)})
            return
        projecten.zet_bezig(project, None)
        meld("klaar", {"woorden": data["aantal_woorden"], "regels": len(data["regels"])})

    draad = threading.Thread(target=werk, name=f"spraak-{project}", daemon=True)
    draad.start()
    return draad


def weg(project: str) -> dict:
    """Spraak uit: overlay en eigen geluid uit de EDL, instelling op uit."""
    pdir = paths.project_dir(project)
    bezig = projecten.is_bezig(project)
    if bezig:
        raise RuntimeError(f"Er loopt al werk aan dit project: {bezig}")
    inst = {**instellingen(project), "aan": False}
    _schrijf_instellingen(project, inst)
    pad = pdir / "edl.json"
    if pad.exists():
        edl = EDL.lees(pad)
        edl.overlay = [o for o in edl.overlay if o.soort != "ondertitels"]
        for b in edl.video:
            if b.reden.endswith("· spraak"):
                b.geluid = b.geluid_voor = b.geluid_na = 0.0
                b.reden = b.reden[: -len(" · spraak")]
        from .monteren import schrijf_met_stap

        schrijf_met_stap(pdir, edl)
    (pdir / "ondertitels.json").unlink(missing_ok=True)
    return stand(project)
