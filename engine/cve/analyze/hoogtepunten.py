"""Hoogtepunten - waar gebeurt er iets, en wat is nieuw?

De segmentscore tot 13-10-2026 mat alleen *kwaliteit*: scherp, belicht,
rustig. Dat kiest nette shots, niet de sterkste. Een montage als GoPro Quik
hem maakt zoekt daarnaast naar *momenten*: de juichkreet, de sprong, de plek
die nog niet in beeld was. Dit bestand meet die drie dingen, mechanisch en
offline (regel 2 en 5 uit CLAUDE.md):

  audiopiek   per meetmoment 0..1: hoeveel luider dan de rest van de clip.
              Gelach, een kreet, een klap, een golf die breekt - allemaal
              een piek boven de eigen achtergrond. Gemeten in dB RMS, zodat
              een stille clip en een luide clip dezelfde schaal krijgen.
  actiepiek   per meetmoment 0..1: hoeveel meer beweging dan de rest van de
              clip. De sprong, de duik, de bocht. `beweging` zelf zegt "er
              beweegt veel"; dit zegt "hier gebeurt het, nu".
  nieuwheid   per clip 0..1: hoe anders deze clip eruitziet dan alle andere
              (dHash). Een derde opname van hetzelfde uitzicht is nieuwheid
              0; het ene shot van de haven ertussen is 1.

De drie staan als `reeks`/clip-velden in `analysis.json` en komen als
onderdelen in de segmentscore (`segmenten.scoor_tijdlijn`). De regisseur
gebruikt ze voor de verhaalboog: opening, drop en slot (`preset._kies`).

Wat hier bewust niet staat: een beeldmodel dat zegt wát er in beeld is. Daar
is de haak `inhoud.py` voor; deze metingen zijn de basis die zonder model
al werkt.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Boven zoveel dB boven de eigen achtergrond telt een moment als volle piek.
PIEK_DB = 10.0
# Onder dit niveau is het ruis, geen geluid: niets kan daar een piek zijn.
STIL_DB = -50.0
# Beweging: zoveel boven het clipgemiddelde (in standaarddeviaties) is een
# volle actiepiek.
ACTIE_SIGMA = 2.0


def luidheid(wav: Path, tijden: list[float], *, sr: int = 16000) -> list[float]:
    """dB RMS op elk meetmoment, uit een mono-wav. Lege lijst als het niet lukt."""
    if not tijden:
        return []
    try:
        import soundfile as sf
    except ImportError:  # pragma: no cover - staat in pyproject
        return []
    try:
        data, bron_sr = sf.read(str(wav), dtype="float32", always_2d=True)
    except (OSError, RuntimeError, ValueError):
        return []
    mono = data.mean(axis=1)
    if mono.size == 0:
        return []
    venster = max(1, int(bron_sr * 0.25))  # een kwart seconde rond elk moment
    uit: list[float] = []
    for t in tijden:
        midden = int(float(t) * bron_sr)
        a = max(0, midden - venster // 2)
        b = min(mono.size, a + venster)
        stuk = mono[a:b]
        rms = float(np.sqrt(np.mean(stuk * stuk))) if stuk.size else 0.0
        uit.append(round(20.0 * np.log10(max(rms, 1e-6)), 2))
    return uit


def audiopiek(db: list[float]) -> list[float]:
    """0..1 per moment: hoeveel luider dan de achtergrond van deze clip.

    De achtergrond is de mediaan van de clip, niet het gemiddelde: één kreet
    trekt een gemiddelde omhoog en maakt zichzelf daarmee kleiner.
    """
    if not db:
        return []
    arr = np.asarray(db, dtype=float)
    achtergrond = float(np.median(arr))
    boven = np.clip((arr - achtergrond) / PIEK_DB, 0.0, 1.0)
    boven[arr < STIL_DB] = 0.0
    return [round(float(x), 3) for x in boven]


def actiepiek(beweging: list[float]) -> list[float]:
    """0..1 per moment: hoeveel meer beweging dan normaal voor deze clip."""
    if not beweging:
        return []
    arr = np.asarray(beweging, dtype=float)
    if arr.size < 3:
        return [0.0] * arr.size
    gem = float(arr.mean())
    sd = float(arr.std())
    if sd < 1e-6:
        return [0.0] * arr.size
    z = (arr - gem) / (sd * ACTIE_SIGMA)
    return [round(float(x), 3) for x in np.clip(z, 0.0, 1.0)]


def nieuwheid(clips: list[dict]) -> dict[str, float]:
    """Per clip 0..1: hoe anders dan de meest gelijkende andere clip.

    Vergelijkt de hash van het midden van elke clip met álle hashes van de
    andere clips. Eén clip is per definitie nieuw (1.0).
    """
    from .beeld import gelijkenis

    hashes: dict[str, list[int]] = {}
    midden: dict[str, int] = {}
    for c in clips:
        hs = [int(h) for h in (c.get("reeks") or {}).get("hashes") or []
              if h is not None]  # 0 is een geldige dhash (egaal beeld)
        if not hs:
            continue
        hashes[c["id"]] = hs
        midden[c["id"]] = hs[len(hs) // 2]
    uit: dict[str, float] = {}
    for c in clips:
        cid = c["id"]
        if cid not in midden:
            uit[cid] = 0.5  # geen beeld gemeten: niet bevoordelen, niet straffen
            continue
        beste = 0.0
        for ander, hs in hashes.items():
            if ander == cid:
                continue
            for h in hs[:: max(1, len(hs) // 8)]:  # acht steekproeven per clip is genoeg
                beste = max(beste, gelijkenis(midden[cid], h))
        uit[cid] = round(1.0 - beste, 3) if len(hashes) > 1 else 1.0
    return uit


def verrijk(clips: list[dict], cache: Path) -> None:
    """Zet audiopiek, actiepiek en nieuwheid in de analyse, ter plekke.

    `cache` is de map met de wav's die `analyse._clip_audio` al gemaakt heeft
    (`<proxy-stem>.wav`); zonder wav blijft de audiopiek nul.
    """
    nieuw = nieuwheid(clips)
    for c in clips:
        reeks = c.setdefault("reeks", {})
        tijden = [float(t) for t in reeks.get("tijden") or []]
        n = len(tijden)
        db: list[float] = []
        if (c.get("audio") or {}).get("heeft_audio") and c.get("proxy"):
            wav = cache / f"{Path(str(c['proxy'])).stem}.wav"
            if wav.exists():
                db = luidheid(wav, tijden)
        reeks["luidheid"] = db
        reeks["audiopiek"] = audiopiek(db) if len(db) == n else [0.0] * n
        reeks["actiepiek"] = actiepiek([float(x) for x in reeks.get("beweging") or []])[:n]
        if len(reeks["actiepiek"]) < n:
            reeks["actiepiek"] = reeks["actiepiek"] + [0.0] * (n - len(reeks["actiepiek"]))
        c["nieuwheid"] = nieuw.get(c["id"], 0.5)


def hoogtepunt(onderdelen: dict) -> float:
    """Eén getal 0..1 voor "hier gebeurt iets": de sterkste van de twee pieken."""
    return max(float(onderdelen.get("audiopiek", 0.0)), float(onderdelen.get("actiepiek", 0.0)))
