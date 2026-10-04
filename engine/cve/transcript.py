"""Transcriptie met whisper.cpp, lokaal.

Per bronclip één keer transcriberen en het resultaat bewaren. De woorden
krijgen daarna hun plek op de tijdlijn door ze door de EDL heen te rekenen —
zo hoeft er na een hermontage niets opnieuw getranscribeerd te worden.

    bronclip  ->  woorden met tijden in de bron   (cache/transcript/<clip>.json)
    EDL       ->  dezelfde woorden op tijdlijntijd
    groepen   ->  leesbare regels van maximaal een paar woorden
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import media, paths
from .edl import EDL

# Ondertitels worden per regel getoond. Deze grenzen komen uit wat leesbaar is
# op een telefoon: kort genoeg om in één oogopslag te lezen.
MAX_TEKENS = 38
MAX_WOORDEN = 7
MAX_REGELDUUR = 3.2
# Een pauze langer dan dit begint een nieuwe regel.
PAUZE = 0.55


class TranscriptFout(RuntimeError):
    pass


@dataclass
class Woord:
    tekst: str
    start: float
    eind: float


@dataclass
class Regel:
    start: float
    eind: float
    tekst: str
    woorden: list[dict]


def _wav(bron: Path, cache: Path) -> Path | None:
    cache.mkdir(parents=True, exist_ok=True)
    return media.haal_audio(bron, cache / f"{bron.stem}.wav", sr=16000, mono=True)


def transcribeer_clip(bron: Path, cache: Path, *, taal: str = "auto", log=print) -> list[Woord]:
    """Transcribeer één bronbestand. Resultaat wordt gecachet."""
    doel = cache / "transcript" / f"{bron.stem}.json"
    if doel.exists():
        d = json.loads(doel.read_text(encoding="utf-8"))
        return [Woord(**w) for w in d["woorden"]]

    binary = paths.whisper_bin()
    model = paths.whisper_model()
    if binary is None or model is None:
        raise TranscriptFout(
            "whisper.cpp of het model ontbreekt. Zie README; `cve doctor` toont wat er mist."
        )

    wav = _wav(bron, cache / "wav")
    if wav is None:
        return []

    doel.parent.mkdir(parents=True, exist_ok=True)
    uit_basis = doel.with_suffix("")
    log(f"  transcriberen: {bron.name}")
    r = subprocess.run(
        [
            str(binary),
            "-m",
            str(model),
            "-f",
            str(wav),
            "-ml",
            "1",  # één woord per segment: dat geeft woord-tijden
            "-sow",  # splits op woordgrenzen
            "--output-json",
            "-of",
            str(uit_basis),
            "-l",
            taal,
            "-np",
            "-nt",
        ],
        capture_output=True,
        text=True,
        timeout=7200,
    )
    ruw = uit_basis.with_suffix(".json")
    if r.returncode != 0 or not ruw.exists():
        laatste = (r.stderr or "").strip().splitlines()[-3:]
        raise TranscriptFout(f"whisper faalde op {bron.name}: " + " | ".join(laatste))

    d = json.loads(ruw.read_text(encoding="utf-8"))
    woorden: list[Woord] = []
    for seg in d.get("transcription", []):
        tekst = (seg.get("text") or "").strip()
        if not tekst or tekst.startswith("[") or tekst in ("(", ")"):
            continue
        offsets = seg.get("offsets") or {}
        woorden.append(
            Woord(
                tekst=tekst,
                start=round(offsets.get("from", 0) / 1000.0, 3),
                eind=round(offsets.get("to", 0) / 1000.0, 3),
            )
        )

    doel.write_text(
        json.dumps({"bestand": bron.name, "woorden": [asdict(w) for w in woorden]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    ruw.unlink(missing_ok=True)
    return woorden


def op_tijdlijn(edl: EDL, projectmap: Path, *, log=print) -> list[Woord]:
    """Alle woorden op montagetijd, door de EDL heen gerekend."""
    cache = projectmap / "cache"
    bronmap = projectmap / "bronnen"

    per_bestand: dict[str, list[Woord]] = {}
    uit: list[Woord] = []

    for blok in edl.video:
        if blok.bestand not in per_bestand:
            pad = bronmap / blok.bestand
            if not pad.exists():
                continue
            try:
                per_bestand[blok.bestand] = transcribeer_clip(pad, cache, log=log)
            except TranscriptFout as e:
                log(f"  {e}")
                per_bestand[blok.bestand] = []

        a, b = blok.bron_start, blok.bron_start + blok.duur * blok.snelheid
        for w in per_bestand[blok.bestand]:
            # Alleen woorden die volledig binnen het gebruikte stuk vallen; een
            # half afgekapt woord onder in beeld leest slechter dan geen woord.
            if w.start < a or w.eind > b:
                continue
            verschuiving = blok.tijdlijn_start - blok.bron_start
            uit.append(
                Woord(
                    tekst=w.tekst,
                    start=round(w.start + verschuiving, 3),
                    eind=round(w.eind + verschuiving, 3),
                )
            )

    uit.sort(key=lambda w: w.start)
    return uit


def groepeer(woorden: list[Woord]) -> list[Regel]:
    """Zet losse woorden om in leesbare regels."""
    regels: list[Regel] = []
    huidig: list[Woord] = []

    def sluit():
        if not huidig:
            return
        regels.append(
            Regel(
                start=huidig[0].start,
                eind=huidig[-1].eind,
                tekst=" ".join(w.tekst for w in huidig),
                woorden=[asdict(w) for w in huidig],
            )
        )
        huidig.clear()

    for w in woorden:
        if huidig:
            tekens = sum(len(x.tekst) + 1 for x in huidig) + len(w.tekst)
            te_lang = tekens > MAX_TEKENS or len(huidig) >= MAX_WOORDEN
            te_traag = w.eind - huidig[0].start > MAX_REGELDUUR
            pauze = w.start - huidig[-1].eind > PAUZE
            zin_af = huidig[-1].tekst.endswith((".", "!", "?"))
            if te_lang or te_traag or pauze or zin_af:
                sluit()
        huidig.append(w)
    sluit()
    return regels


def maak(project: str, *, log=print) -> dict:
    """Bouw het ondertitelbestand voor een project."""
    pdir = paths.project_dir(project)
    edl = EDL.lees(pdir / "edl.json")
    log("Transcript maken (lokaal, whisper.cpp)...")
    woorden = op_tijdlijn(edl, pdir, log=log)
    regels = groepeer(woorden)
    data = {
        "versie": 1,
        "aantal_woorden": len(woorden),
        "regels": [asdict(r) for r in regels],
    }
    (pdir / "ondertitels.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    log(f"{len(woorden)} woorden, {len(regels)} regels")
    return data
