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


# Langer dan dit duurt geen woord; whisper rekt het laatste woord van een
# stuk stilte soms tot het einde van zijn 30-secondenvenster op.
MAX_WOORDDUUR = 1.5
# Zoveel vóór de snede mag een woord beginnen en toch bij het shot horen.
RANDSPELING = 0.1
# Kortere stiltes tussen woorden worden dichtgezet (karaoke knippert anders).
GAATJE = 0.3


def _duur_van(wav: Path) -> float | None:
    try:
        return media.probe(wav).duur
    except Exception:  # noqa: BLE001 — zonder duur alleen de andere grenzen
        return None


def _begrens(woorden: list[Woord], clipduur: float | None) -> list[Woord]:
    """Houd de woordtijden binnen de clip en elkaar.

    Een woord eindigt uiterlijk waar het volgende begint, en nooit meer dan
    `MAX_WOORDDUUR` na zijn eigen begin; het laatste woord eindigt binnen de
    clip. Zonder dit stond "ondertitels." van 6,03 tot 30,0 s op een clip van
    zes seconden en viel hij daarmee buiten elk shot.
    """
    uit: list[Woord] = []
    for i, w in enumerate(woorden):
        eind = w.eind
        if i + 1 < len(woorden):
            volgende = woorden[i + 1].start
            eind = min(eind, volgende)
            # Een gaatje van een paar tienden tussen twee woorden dichtzetten:
            # anders knippert de karaoke-markering tussen elk woord.
            if 0 < volgende - eind < GAATJE:
                eind = volgende
        eind = min(eind, w.start + MAX_WOORDDUUR)
        if clipduur is not None:
            eind = min(eind, clipduur)
        eind = max(eind, w.start + 0.05)
        uit.append(Woord(tekst=w.tekst, start=w.start, eind=round(eind, 3)))
    return uit


CACHE_VERSIE = 2


def woorden_uit_tokens(d: dict) -> list[Woord]:
    """Woorden uit whispers volledige JSON (`--output-json-full`).

    Whisper denkt in tokens, niet in woorden: " ond", "ert", "itels" is één
    woord, en "," of "." plakt aan het woord ervoor. Een token met een
    spatie vooraan begint een nieuw woord. Speciale tokens (`[_BEG_]`,
    `[_TT_…]`) en lege tekst vallen weg. Het begin van een woord is het begin
    van zijn eerste token; het einde dat van zijn laatste — `_begrens` maakt
    het daarna netjes.
    """
    woorden: list[Woord] = []
    huidig: list[str] = []
    start = eind = 0.0

    def sluit() -> None:
        tekst = "".join(huidig).strip()
        if tekst and not tekst.startswith("["):
            woorden.append(Woord(tekst=tekst, start=round(start, 3), eind=round(eind, 3)))
        huidig.clear()

    for seg in d.get("transcription", []):
        for tok in seg.get("tokens") or []:
            tekst = tok.get("text") or ""
            if not tekst or tekst.startswith("[_") or tekst.strip() == "":
                continue
            off = tok.get("offsets") or {}
            van = float(off.get("from", 0)) / 1000.0
            tot = float(off.get("to", off.get("from", 0))) / 1000.0
            if _is_leesteken(tekst):
                tekst = tekst.strip()  # "ondertitels ." wordt "ondertitels."
            nieuw_woord = tekst.startswith(" ")
            if nieuw_woord and huidig:
                sluit()
            if not huidig:
                start = van
            huidig.append(tekst)
            eind = max(eind if huidig[:-1] else van, tot)
        sluit()  # een segment eindigt altijd op een woordgrens
    return woorden


def _is_leesteken(tekst: str) -> bool:
    return tekst.strip() != "" and all(not c.isalnum() for c in tekst.strip())


def heeft_cache(bron: Path, cache: Path, *, taal: str = "auto") -> bool:
    """Staat er een bruikbaar transcript voor `bron`? Zonder whisper te starten."""
    doel = cache / "transcript" / f"{bron.stem}.json"
    try:
        d = json.loads(doel.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return d.get("versie") == CACHE_VERSIE and d.get("taal", "auto") == taal


def transcribeer_clip(bron: Path, cache: Path, *, taal: str = "auto", log=print) -> list[Woord]:
    """Transcribeer één bronbestand. Resultaat wordt gecachet."""
    doel = cache / "transcript" / f"{bron.stem}.json"
    if doel.exists():
        try:
            d = json.loads(doel.read_text(encoding="utf-8"))
        except ValueError:
            d = {}
        # Caches van vóór versie 2 hebben de scheve tijden van `-ml 1`.
        # En de taal hoort bij de sleutel: wie "nl" kiest omdat "auto" de
        # verkeerde taal hoorde, moet een ander transcript krijgen (review
        # 14-10-2026). Caches zonder taal zijn met "auto" gemaakt.
        if d.get("versie") == CACHE_VERSIE and d.get("taal", "auto") == taal:
            return [Woord(**w) for w in d["woorden"]]

    binary = paths.whisper_bin()
    model = paths.whisper_model()
    if binary is None or model is None:
        raise TranscriptFout(
            "whisper.cpp of het model ontbreekt. Zie README; `cve doctor` toont wat er mist."
        )

    wav = _wav(bron, cache / "wav")
    doel.parent.mkdir(parents=True, exist_ok=True)
    if wav is None:
        # Geen geluidsspoor (een drone-clip): ook dat is een uitkomst, en die
        # hoort in de cache. Zonder dit bestand dacht `heeft_cache()` dat het
        # transcript ontbrak, en legde stap 4 de ondertitels nooit meer opnieuw
        # zodra er één stille clip in de montage stond (Codex, 15-10-2026).
        doel.write_text(
            json.dumps({"versie": CACHE_VERSIE, "bestand": bron.name, "taal": taal,
                        "woorden": [], "geen_geluid": True}, ensure_ascii=False),
            encoding="utf-8",
        )
        return []

    # Een eigen naam voor wat whisper schrijft. Tot 13-10-2026 was dat
    # `<stem>.json` — hetzelfde pad als de cache, die daarna met `unlink`
    # weer verdween. Elke hermontage transcribeerde zo álle clips opnieuw.
    uit_basis = doel.with_name(f"{doel.stem}.ruw")
    log(f"  transcriberen: {bron.name}")
    r = subprocess.run(
        [
            str(binary),
            "-m",
            str(model),
            "-f",
            str(wav),
            # De volledige JSON, met per token een tijd. Tot 14-10-2026 stond
            # hier `-ml 1 -sow` (één woord per segment), en dan rekt whisper
            # elk woord op tot het volgende segment: "dit is een proef" kwam op
            # 5,5–8,4 s terwijl het op 0,8–1,5 s gezegd werd. De tokentijden
            # kloppen wél (nagemeten tegen silencedetect).
            "--output-json-full",
            "-of",
            str(uit_basis),
            "-l",
            taal,
            "-np",
        ],
        capture_output=True,
        text=True,
        timeout=7200,
    )
    # Niet `with_suffix`: dat ziet ".ruw" als achtervoegsel en vervangt het.
    ruw = uit_basis.parent / f"{uit_basis.name}.json"
    if r.returncode != 0 or not ruw.exists():
        laatste = (r.stderr or "").strip().splitlines()[-3:]
        raise TranscriptFout(f"whisper faalde op {bron.name}: " + " | ".join(laatste))

    d = json.loads(ruw.read_text(encoding="utf-8"))
    woorden = _begrens(woorden_uit_tokens(d), _duur_van(wav))

    doel.write_text(
        json.dumps({"versie": CACHE_VERSIE, "bestand": bron.name, "taal": taal,
                    "woorden": [asdict(w) for w in woorden]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    ruw.unlink(missing_ok=True)
    return woorden


def op_tijdlijn(edl: EDL, projectmap: Path, *, taal: str = "auto", log=print) -> list[Woord]:
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
                per_bestand[blok.bestand] = transcribeer_clip(pad, cache, taal=taal, log=log)
            except TranscriptFout as e:
                log(f"  {e}")
                per_bestand[blok.bestand] = []

        a, b = blok.bron_start, blok.bron_start + blok.bron_lengte
        # Op dubbele snelheid komt een woord op de helft van zijn brontijd;
        # tot 13-10-2026 schoof hier alleen de offset mee, niet de schaal.
        snelheid = blok.bron_lengte / blok.duur if blok.duur > 0 else 1.0
        for w in per_bestand[blok.bestand]:
            # Een woord hoort bij het shot waarin het begint (met een
            # tiende seconde speling voor de aanzet); het einde wordt op de
            # snede geklemd. De oude regel "helemaal binnen het stuk" liet op
            # shots van twee seconden de helft van de woorden vallen.
            if w.start < a - RANDSPELING or w.start >= b:
                continue
            eind = min(w.eind, b)
            start = max(w.start, a)
            if eind - start < 0.05:
                continue
            uit.append(
                Woord(
                    tekst=w.tekst,
                    start=round(blok.tijdlijn_start + (start - a) / snelheid, 3),
                    eind=round(blok.tijdlijn_start + (eind - a) / snelheid, 3),
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
