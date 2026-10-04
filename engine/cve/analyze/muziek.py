"""Fase 1c - muziekanalyse.

De muziek is de ruggengraat van een actie/vlog-montage. Wat we eruit halen:

  bpm         tempo
  beats       tijdstip van elke tel
  maten       elke 4e tel (downbeat) - hier snijden voelt natuurlijk
  energie     RMS per beat, genormaliseerd; hieruit volgen de secties
  secties     rustig / opbouw / hoog, met grenzen
  drops       momenten waar de energie sterk omhoog springt

Alles lokaal met librosa. Geen model, geen tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np

SR = 22050  # genoeg voor tempo en energie, en snel


@dataclass
class Sectie:
    start: float
    eind: float
    niveau: str  # "rustig" | "opbouw" | "hoog"
    energie: float


@dataclass
class Muziek:
    bestand: str
    duur: float
    bpm: float
    beats: list[float] = field(default_factory=list)
    maten: list[float] = field(default_factory=list)
    energie_per_beat: list[float] = field(default_factory=list)
    secties: list[Sectie] = field(default_factory=list)
    drops: list[float] = field(default_factory=list)

    @property
    def beat_duur(self) -> float:
        return 60.0 / self.bpm if self.bpm else 0.0


def _niveau(waarde: float) -> str:
    if waarde < 0.38:
        return "rustig"
    if waarde < 0.68:
        return "opbouw"
    return "hoog"


def _vloeiend(x: np.ndarray, venster: int) -> np.ndarray:
    if venster < 2 or len(x) < venster:
        return x
    kern = np.ones(venster) / venster
    return np.convolve(x, kern, mode="same")


def _tot_het_eind(beats: list[float], duur: float, bpm: float) -> list[float]:
    """Verleng het tel-raster tot het eind van de track.

    `beat_track` stopt waar het ritme wegvalt. Bij de testtrack hield hij op
    bij 194,9 s terwijl de muziek 208,5 s duurt: 13,6 s uitloop zonder raster.
    De regie snijdt daar wel door - `einde` is de muziekduur - en zonder tellen
    om op te leggen lagen die laatste snedes tot 10,9 s naast de tel.

    Verlengen gebeurt met de gemeten gemiddelde tel-afstand, niet met 60/BPM:
    de gemeten afstand is 0,4918 s waar 60/123,05 BPM 0,4876 s geeft, en over
    dertien seconden is dat verschil ruim twee tellen.

    Bij een track die halverwege van tempo wisselt raadt dit mis. Dat is nog
    altijd beter dan geen raster: dan ligt er niets om op te snijden.
    """
    if len(beats) < 2:
        return beats
    stap = (beats[-1] - beats[0]) / (len(beats) - 1)
    if stap <= 0:
        stap = 60.0 / bpm if bpm else 0.5
    verlengd = list(beats)
    t = beats[-1] + stap
    while t < duur:
        verlengd.append(t)
        t += stap
    return verlengd


def analyseer(pad: Path, *, maat: int = 4) -> Muziek:
    y, sr = librosa.load(str(pad), sr=SR, mono=True)
    duur = float(len(y) / sr)

    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset, sr=sr, units="frames")
    bpm = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    beats = _tot_het_eind(beats, duur, bpm)

    # Energie per beat: RMS over het venster tot de volgende tel.
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_tijden = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    energie: list[float] = []
    for i, t in enumerate(beats):
        eind = beats[i + 1] if i + 1 < len(beats) else duur
        masker = (rms_tijden >= t) & (rms_tijden < eind)
        energie.append(float(rms[masker].mean()) if masker.any() else 0.0)

    arr = np.asarray(energie, dtype=float)
    if arr.size and arr.max() > 0:
        # Percentiel-normalisatie: robuuster dan delen door het maximum,
        # want een enkele piek zou anders de hele schaal platslaan.
        laag, hoog = np.percentile(arr, 5), np.percentile(arr, 95)
        arr = np.clip((arr - laag) / max(1e-9, hoog - laag), 0.0, 1.0)
    energie_n = [round(float(v), 4) for v in arr]

    # Maten: elke `maat`e tel. Fase kiezen op de sterkste onset-som, zodat
    # de eerste maat op een echte downbeat valt in plaats van willekeurig.
    maten: list[float] = []
    if beats:
        onset_bij_beat = np.interp(
            beats,
            librosa.frames_to_time(np.arange(len(onset)), sr=sr),
            onset,
        )
        beste_fase, beste_som = 0, -1.0
        for fase in range(maat):
            som = float(onset_bij_beat[fase::maat].sum())
            if som > beste_som:
                beste_fase, beste_som = fase, som
        maten = [beats[i] for i in range(beste_fase, len(beats), maat)]

    # Secties: gladgestreken energie, dan aaneengesloten stukken van gelijk niveau.
    secties: list[Sectie] = []
    if energie_n:
        glad = _vloeiend(np.asarray(energie_n), venster=8)
        huidig = _niveau(float(glad[0]))
        start = beats[0]
        buffer = [float(glad[0])]
        for i in range(1, len(glad)):
            n = _niveau(float(glad[i]))
            if n != huidig:
                eind = beats[i]
                if eind - start >= 4.0:  # secties korter dan 4s zijn ruis
                    secties.append(
                        Sectie(round(start, 3), round(eind, 3), huidig, round(np.mean(buffer), 3))
                    )
                    start = eind
                    huidig = n
                    buffer = []
            buffer.append(float(glad[i]))
        secties.append(
            Sectie(round(start, 3), round(duur, 3), huidig, round(float(np.mean(buffer)), 3))
        )

    # Drops: sterke sprong omhoog in gladgestreken energie.
    drops: list[float] = []
    if len(energie_n) > 10:
        glad = _vloeiend(np.asarray(energie_n), venster=4)
        sprong = np.diff(glad, prepend=glad[0])
        drempel = max(0.12, float(np.percentile(sprong, 97)))
        laatste = -99.0
        for i, s in enumerate(sprong):
            if s >= drempel and beats[i] - laatste > 8.0:
                drops.append(round(beats[i], 3))
                laatste = beats[i]

    return Muziek(
        bestand=pad.name,
        duur=round(duur, 3),
        bpm=round(bpm, 2),
        beats=[round(b, 3) for b in beats],
        maten=[round(m, 3) for m in maten],
        energie_per_beat=energie_n,
        secties=secties,
        drops=drops,
    )


def snijraster(m: Muziek, *, per_maat: float = 1.0) -> list[float]:
    """Voorgestelde snijmomenten.

    Standaard elke maat; in hoge secties elke halve maat, in rustige elke twee.
    Dit is een voorstel, geen wet - de regisseur mag ervan afwijken.
    """
    if not m.maten:
        return []
    niveau_bij = {}
    for s in m.secties:
        niveau_bij[(s.start, s.eind)] = s.niveau

    def niveau_op(t: float) -> str:
        for (a, b), n in niveau_bij.items():
            if a <= t < b:
                return n
        return "opbouw"

    factor = {"rustig": 2.0, "opbouw": 1.0, "hoog": 0.5}
    uit: list[float] = []
    i = 0
    while i < len(m.maten):
        t = m.maten[i]
        uit.append(t)
        stap = max(1, int(round(factor[niveau_op(t)] * per_maat)))
        i += stap
    return uit


def samenvatting(m: Muziek) -> str:
    regels = [
        f"{m.bestand}",
        f"{m.duur:.1f}s  ·  {m.bpm:.1f} BPM  ·  {len(m.beats)} tellen  ·  {len(m.maten)} maten",
        f"maatduur {m.beat_duur * 4:.2f}s  ·  {len(m.drops)} drops",
        "",
        "secties:",
    ]
    for s in m.secties:
        regels.append(f"  {s.start:7.1f} - {s.eind:7.1f}s  {s.niveau:8} energie {s.energie:.2f}")
    if m.drops:
        regels.append("")
        regels.append("drops: " + ", ".join(f"{d:.1f}s" for d in m.drops))
    return "\n".join(regels)
