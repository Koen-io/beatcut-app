"""Fase 1b - beeldanalyse.

Alles mechanisch meetbaar aan het beeld, gemeten op de proxy. Geen model,
geen frames naar buiten. Per clip leveren we shots plus een metriek per
seconde, zodat de regisseur later per moment kan kiezen.

Metrieken (allemaal 0..1 tenzij anders vermeld):
  scherpte    variance-of-Laplacian, genormaliseerd
  belichting  1.0 = goed belicht, lager bij clipping of te donker
  beweging    gemiddelde optical-flow-magnitude (onderwerp + camera)
  shake       hoogfrequente variatie in camerabeweging (hoog = wiebelig)
  vlakheid    hoe weinig detail het beeld heeft (lucht, muur, onscherpte)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import kalibratie as ijk

# Analyse-resolutie. Klein genoeg om snel te zijn, groot genoeg voor scherpte.
ANALYSE_BREEDTE = 320
# Aantal metingen per seconde.
SAMPLES_PER_SEC = 4


@dataclass
class Shot:
    index: int
    start: float
    eind: float

    @property
    def duur(self) -> float:
        return self.eind - self.start


@dataclass
class ClipBeeld:
    duur: float
    fps: float
    tijden: list[float] = field(default_factory=list)
    scherpte: list[float] = field(default_factory=list)
    belichting: list[float] = field(default_factory=list)
    beweging: list[float] = field(default_factory=list)
    shake: list[float] = field(default_factory=list)
    vlakheid: list[float] = field(default_factory=list)
    # Perceptuele vingerafdruk per meting (64-bit dHash als int).
    # Hiermee herkennen we bijna-identieke beelden zonder ze op te slaan.
    hashes: list[int] = field(default_factory=list)
    # Dominante kleuren per meting als (h, s, v) in 0..1
    kleur: list[tuple[float, float, float]] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)


def dhash(grijs: np.ndarray, *, zijde: int = 8) -> int:
    """Difference hash: 64 bits die zeggen hoe het beeld eruitziet.

    Twee beelden met een kleine Hamming-afstand lijken sterk op elkaar. Dit
    voorkomt dat de montage twee bijna identieke shots achter elkaar zet.
    """
    klein = cv2.resize(grijs, (zijde + 1, zijde), interpolation=cv2.INTER_AREA)
    bits = klein[:, 1:] > klein[:, :-1]
    waarde = 0
    for bit in bits.flatten():
        waarde = (waarde << 1) | int(bit)
    return int(waarde)


def hamming(a: int, b: int) -> int:
    """Aantal verschillende bits. 0 = identiek, 64 = volledig anders."""
    return bin(a ^ b).count("1")


def gelijkenis(a: int, b: int) -> float:
    """0..1, waarbij 1.0 identiek is."""
    return 1.0 - hamming(a, b) / 64.0


def _dominante_kleur(bgr: np.ndarray) -> tuple[float, float, float]:
    """Gemiddelde tint, verzadiging en helderheid als 0..1.

    Tint wordt circulair gemiddeld, anders komt rood (0 en 1) op groen uit.
    """
    hsv = cv2.cvtColor(cv2.resize(bgr, (64, 36)), cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(float) * (2 * np.pi / 180.0)
    s = hsv[..., 1].astype(float) / 255.0
    v = hsv[..., 2].astype(float) / 255.0
    # Weeg tint met verzadiging: grijze pixels hebben geen betekenisvolle tint.
    gewicht = s.flatten()
    if gewicht.sum() < 1e-6:
        return (0.0, 0.0, round(float(v.mean()), 4))
    hoek = np.arctan2(
        np.average(np.sin(h.flatten()), weights=gewicht),
        np.average(np.cos(h.flatten()), weights=gewicht),
    )
    tint = float((hoek % (2 * np.pi)) / (2 * np.pi))
    return (round(tint, 4), round(float(s.mean()), 4), round(float(v.mean()), 4))


def _belichtingsscore(grijs: np.ndarray) -> float:
    """1.0 bij nette spreiding; straft uitgebrande en dichtgelopen beelden."""
    hist = cv2.calcHist([grijs], [0], None, [64], [0, 256]).ravel()
    totaal = hist.sum()
    if totaal <= 0:
        return 0.0
    hist = hist / totaal
    clip_hoog = float(hist[-2:].sum())
    clip_laag = float(hist[:2].sum())
    gemiddeld = float(grijs.mean()) / 255.0
    midden = 1.0 - min(1.0, abs(gemiddeld - ijk.BELICHTING_DOEL) / ijk.BELICHTING_MARGE)
    straf = min(1.0, (clip_hoog + clip_laag) * ijk.CLIPPING_STRAF)
    return float(max(0.0, midden * (1.0 - straf)))


def _getal(x, standaard: float) -> float:
    """Een bruikbaar positief getal, of de standaard (ook bij NaN en oneindig)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return standaard
    return v if math.isfinite(v) and v > 0 else standaard


def analyseer_clip(proxy: Path, *, samples_per_sec: int = SAMPLES_PER_SEC) -> ClipBeeld:
    """Loop de proxy een keer door en meet alles onderweg."""
    cap = cv2.VideoCapture(str(proxy))
    if not cap.isOpened():
        raise RuntimeError(f"Kan proxy niet openen: {proxy}")

    # OpenCV geeft soms NaN in plaats van 0 (gezien op de Intel-runner,
    # 03-10-2026): `x or 30` laat NaN door, want NaN is waar.
    fps = _getal(cap.get(cv2.CAP_PROP_FPS), 30.0)
    n_frames = int(_getal(cap.get(cv2.CAP_PROP_FRAME_COUNT), 0.0))
    duur = n_frames / fps if fps else 0.0

    stap = max(1, int(round(fps / samples_per_sec)))
    uit = ClipBeeld(duur=round(duur, 3), fps=round(fps, 3))

    vorige_klein: np.ndarray | None = None
    flow_reeks: list[float] = []
    idx = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stap != 0:
            idx += 1
            continue

        h, w = frame.shape[:2]
        schaal = ANALYSE_BREEDTE / max(1, w)
        klein = cv2.resize(frame, (ANALYSE_BREEDTE, max(1, int(h * schaal))))
        grijs = cv2.cvtColor(klein, cv2.COLOR_BGR2GRAY)

        var = float(cv2.Laplacian(grijs, cv2.CV_64F).var())
        uit.scherpte.append(round(ijk.scherpte(var), 4))
        uit.vlakheid.append(round(ijk.vlakheid(float(grijs.std())), 4))
        uit.belichting.append(round(_belichtingsscore(grijs), 4))
        uit.hashes.append(dhash(grijs))
        uit.kleur.append(_dominante_kleur(klein))

        if vorige_klein is not None:
            flow = cv2.calcOpticalFlowFarneback(
                vorige_klein, grijs, None, 0.5, 2, 13, 2, 5, 1.1, 0
            )
            mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
            gem = float(mag.mean())
            flow_reeks.append(gem)
            uit.beweging.append(round(ijk.beweging(gem), 4))
        else:
            uit.beweging.append(0.0)

        uit.tijden.append(round(idx / fps, 3))
        vorige_klein = grijs
        idx += 1

    cap.release()

    # Shake: hoe grillig verandert de beweging van meting op meting.
    uit.shake = _shake_uit_flow(flow_reeks, len(uit.tijden))
    return uit


def _shake_uit_flow(flow: list[float], lengte: int) -> list[float]:
    """Hoogfrequente variatie in bewegingssnelheid = wiebelen."""
    if len(flow) < 3:
        return [0.0] * lengte
    arr = np.asarray(flow, dtype=float)
    verschil = np.abs(np.diff(arr, prepend=arr[0]))
    venster = 5
    kern = np.ones(venster) / venster
    glad = np.convolve(verschil, kern, mode="same")
    uit = [round(ijk.shake(float(v)), 4) for v in glad]
    # Eerste meting had geen flow; lijn de lengte uit.
    uit = [uit[0]] + uit
    if len(uit) < lengte:
        uit += [uit[-1]] * (lengte - len(uit))
    return uit[:lengte]


def detecteer_shots(proxy: Path, *, drempel: float = 27.0, min_lengte: float = 0.6) -> list[Shot]:
    """Shot-grenzen via PySceneDetect (contentgebaseerd)."""
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(proxy))
    mgr = SceneManager()
    fps = _getal(video.frame_rate, 30.0)
    mgr.add_detector(
        ContentDetector(threshold=drempel, min_scene_len=int(max(1, min_lengte * fps)))
    )
    try:
        mgr.detect_scenes(video, show_progress=False)
    except (ValueError, OverflowError) as e:
        # De OpenCV-backend van PySceneDetect rekent met CAP_PROP_POS_MSEC, en
        # sommige OpenCV-builds geven daar NaN (Intel-Mac, 03-10-2026: "cannot
        # convert float NaN to integer"). Dan geen shotgrenzen, maar wel een
        # analyse: de hele clip als één shot; de segmentatie knipt hem daarna
        # toch in vensters.
        import sys

        print(f"shotdetectie overgeslagen voor {proxy.name}: {e}", file=sys.stderr)
        from .. import media

        return [Shot(index=0, start=0.0, eind=round(media.probe(proxy).duur, 3))]
    scenes = mgr.get_scene_list()

    if not scenes:
        duur = float(video.duration.get_seconds()) if video.duration else 0.0
        return [Shot(index=0, start=0.0, eind=round(duur, 3))]

    return [
        Shot(index=i, start=round(a.get_seconds(), 3), eind=round(b.get_seconds(), 3))
        for i, (a, b) in enumerate(scenes)
    ]


def per_shot_samenvatting(beeld: ClipBeeld) -> list[dict]:
    """Vat de metingen samen per shot. Dit is wat het model uiteindelijk leest."""
    if not beeld.tijden:
        return []
    t = np.asarray(beeld.tijden)
    reeksen = {
        "scherpte": np.asarray(beeld.scherpte),
        "belichting": np.asarray(beeld.belichting),
        "beweging": np.asarray(beeld.beweging),
        "shake": np.asarray(beeld.shake),
        "vlakheid": np.asarray(beeld.vlakheid),
    }

    uit: list[dict] = []
    shots = beeld.shots or [Shot(0, 0.0, beeld.duur)]
    for shot in shots:
        masker = (t >= shot.start) & (t < max(shot.eind, shot.start + 1e-3))
        if not masker.any():
            masker = np.zeros_like(t, dtype=bool)
            masker[min(len(t) - 1, int(shot.start))] = True
        rij = {
            "shot": shot.index,
            "start": shot.start,
            "eind": shot.eind,
            "duur": round(shot.duur, 3),
        }
        for naam, reeks in reeksen.items():
            waarden = reeks[masker]
            rij[naam] = round(float(waarden.mean()), 4)
            if naam in ("beweging", "scherpte"):
                rij[f"{naam}_piek"] = round(float(waarden.max()), 4)
        uit.append(rij)
    return uit
