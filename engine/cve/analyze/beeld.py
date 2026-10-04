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

En per meetmoment één aandachtspunt (`aandacht_x`, `aandacht_y`, 0..1 over het
beeld): waar het onderwerp staat. Daarmee kan een liggende clip in een staand
canvas om het onderwerp heen gesneden worden in plaats van door het midden.
Zie `cve/kader.py`.
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
    # Aandachtspunt per meting: waar staat het onderwerp, 0..1 over breedte
    # en hoogte van het beeld. Gladgestreken, zodat een crop die dit volgt
    # niet schokt.
    aandacht_x: list[float] = field(default_factory=list)
    aandacht_y: list[float] = field(default_factory=list)
    # 1 waar het punt van een gezicht komt, 0 waar het geraden is uit
    # beweging of detail.
    aandacht_gezicht: list[int] = field(default_factory=list)
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


# --------------------------------------------------------------------------
# Aandachtspunt: waar staat het onderwerp?
# --------------------------------------------------------------------------
#
# Drie bronnen, in deze volgorde van betrouwbaarheid:
#
#   1. een gezicht - dan is er geen twijfel waar je naar kijkt;
#   2. beweging die afwijkt van de rest van het beeld - een rijdende auto, een
#      lopend kind. De mediaan gaat eraf, want die is de camerabeweging zelf:
#      bij een pan beweegt *alles*, en dan zegt een zwaartepunt niets;
#   3. detail - waar de randen zitten. Lucht en wegdek zijn vlak, het
#      onderwerp niet. Zwakke aanwijzing, maar beter dan blind het midden.
#
# Alles wordt gemeten op het 320 px brede analysebeeld dat er toch al is.

_cascade: object = None


def _gezichtsdetector():
    """De Haar-cascade van OpenCV, of None als die er niet is.

    Een cascade is een bestand dat met opencv-python meekomt; in een uitgeklede
    bouw kan het ontbreken. Dan vallen we terug op beweging en detail in plaats
    van de hele analyse te laten vallen.
    """
    global _cascade
    if _cascade is None:
        try:
            pad = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            det = cv2.CascadeClassifier(str(pad))
            _cascade = False if det.empty() else det
        except (AttributeError, cv2.error):
            _cascade = False
    return None if _cascade is False else _cascade


def _zwaartepunt(gewicht: np.ndarray) -> tuple[float, float] | None:
    """Het gewogen midden van een beeldvlak, als fractie 0..1."""
    totaal = float(gewicht.sum())
    if not math.isfinite(totaal) or totaal <= 1e-9:
        return None
    h, b = gewicht.shape[:2]
    kol = gewicht.sum(axis=0)
    rij = gewicht.sum(axis=1)
    x = float((kol * np.arange(b)).sum()) / totaal / max(1, b - 1)
    y = float((rij * np.arange(h)).sum()) / totaal / max(1, h - 1)
    return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))


def _gezichtspunt(grijs: np.ndarray) -> tuple[float, float] | None:
    """Het midden van de gezichten, het grootste gezicht het zwaarst."""
    det = _gezichtsdetector()
    if det is None:
        return None
    h, b = grijs.shape[:2]
    zijde = max(24, int(b * 0.08))
    try:
        vakken = det.detectMultiScale(grijs, 1.2, 5, minSize=(zijde, zijde))
    except cv2.error:
        return None
    if len(vakken) == 0:
        return None
    gewicht = sum(float(w * hh) for _, _, w, hh in vakken)
    x = sum((vx + w / 2) * w * hh for vx, _, w, hh in vakken) / gewicht
    y = sum((vy + hh / 2) * w * hh for _, vy, w, hh in vakken) / gewicht
    return min(1.0, max(0.0, x / b)), min(1.0, max(0.0, y / h))


def _aandachtspunt(
    grijs: np.ndarray, laplace: np.ndarray, flow: np.ndarray | None
) -> tuple[float, float, int]:
    """Eén aandachtspunt: (x, y, kwam-van-een-gezicht)."""
    punt = _gezichtspunt(grijs)
    if punt is not None:
        return punt[0], punt[1], 1

    if flow is not None:
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        eigen = np.clip(mag - float(np.median(mag)), 0.0, None)
        # Alleen als er echt iets uitsteekt. Onder deze drempel is het ruis in
        # de flow en zou het zwaartepunt per meting rondspringen.
        if float(eigen.max() if eigen.size else 0.0) > 0.25:
            punt = _zwaartepunt(eigen)
            if punt is not None:
                return punt[0], punt[1], 0

    punt = _zwaartepunt(np.abs(laplace))
    if punt is None:
        return 0.5, 0.5, 0
    return punt[0], punt[1], 0


# Over hoeveel metingen het aandachtspunt wordt uitgesmeerd. Bij vier metingen
# per seconde is 7 bijna twee seconden: een gezicht dat één meting wegvalt
# verschuift het kader niet, en een crop die dit volgt schokt niet.
GLAD_VENSTER = 7


def _gladgestreken(waarden: list[float], venster: int = GLAD_VENSTER) -> list[float]:
    """Lopend gemiddelde, met de randen vastgehouden in plaats van naar nul."""
    if len(waarden) < 2:
        return [round(v, 4) for v in waarden]
    arr = np.asarray(waarden, dtype=float)
    n = min(venster, len(arr))
    kern = np.ones(n) / n
    # `edge` aan de randen: `convolve(mode="same")` vult met nullen en trekt
    # het eerste en laatste punt dan naar de linkerbovenhoek.
    rand = n // 2
    gevuld = np.pad(arr, (rand, rand), mode="edge")
    glad = np.convolve(gevuld, kern, mode="same")[rand : rand + len(arr)]
    return [round(float(min(1.0, max(0.0, v))), 4) for v in glad]


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

        laplace = cv2.Laplacian(grijs, cv2.CV_64F)
        var = float(laplace.var())
        uit.scherpte.append(round(ijk.scherpte(var), 4))
        uit.vlakheid.append(round(ijk.vlakheid(float(grijs.std())), 4))
        uit.belichting.append(round(_belichtingsscore(grijs), 4))
        uit.hashes.append(dhash(grijs))
        uit.kleur.append(_dominante_kleur(klein))

        flow = None
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

        ax, ay, gezicht = _aandachtspunt(grijs, laplace, flow)
        uit.aandacht_x.append(ax)
        uit.aandacht_y.append(ay)
        uit.aandacht_gezicht.append(gezicht)

        uit.tijden.append(round(idx / fps, 3))
        vorige_klein = grijs
        idx += 1

    cap.release()

    # Shake: hoe grillig verandert de beweging van meting op meting.
    uit.shake = _shake_uit_flow(flow_reeks, len(uit.tijden))
    # Het aandachtspunt pas aan het eind gladstrijken: een crop die per meting
    # een andere kant op schiet is erger dan een crop die te laat volgt.
    uit.aandacht_x = _gladgestreken(uit.aandacht_x)
    uit.aandacht_y = _gladgestreken(uit.aandacht_y)
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
