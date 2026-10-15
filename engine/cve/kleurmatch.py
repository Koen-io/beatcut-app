"""Kleurafstemming tussen clips — shot-matching, zoals een colorist het doet
vóór de look erop gaat.

Een montage uit twintig clips heeft twintig belichtingen en witbalansen: de
ene opname in de schaduw blauwig en donker, de volgende in de zon warm en
licht. Eén LUT daaroverheen maakt dat niet gelijk; het maakt het verschil
alleen stijlvoller. Daarom eerst afstemmen: elke clip krijgt een kleine
versterking per kanaal zodat zijn gemiddelde helderheid en zijn grijsbalans
op die van de montage komen te liggen. Daarna is de look één look.

Wat het is: per shot drie getallen, {"r", "g", "b"}, waarmee het beeld
vermenigvuldigd wordt. Geklemd op ±25 % — meer is geen afstemming meer maar
een kleurbewerking, en die hoort bij de look. Berekend uit `reeks.balans`
(gemiddeld r, g, b per meetmoment, `analyze/beeld.py`) over het stuk clip dat
het shot gebruikt; het doel is de mediaan van alle shots in de montage, met
de helderheid verrekend in lineair licht (gamma 2,2), niet in codes.

Waar het toegepast wordt, twee keer hetzelfde:
  - export: `render._kleurmatch_filter` → ffmpeg `colorchannelmixer` aan het
    eind van de blokketen, vóór de compositor de look erover legt;
  - voorvertoning: `u.kleurA`/`u.kleurB` in de shader (`o_kleur`).

`EDL.afstemmen` zet het aan of uit; de getallen blijven staan.
"""

from __future__ import annotations

import numpy as np

from .edl import EDL

GAMMA = 2.2
# Niet meer dan dit per kanaal. Een clip die 40 % te donker is krijgt 25 %
# erbij en blijft wat donkerder — beter dan ruis omhoog trekken.
MAX_VERSTERKING = 1.25
MIN_VERSTERKING = 0.80
# Onder dit verschil met het doel doen we niets: een shot dat al goed ligt
# krijgt geen getallen, en een EDL van vóór deze functie blijft gelijk.
DREMPEL = 0.02


def _lin(x: np.ndarray) -> np.ndarray:
    return np.power(np.clip(x, 0.0, 1.0), GAMMA)


def _van_lin(x: np.ndarray) -> np.ndarray:
    return np.power(np.clip(x, 0.0, 1.0), 1.0 / GAMMA)


def gemiddelde_balans(clip: dict, bron_start: float, bron_eind: float) -> np.ndarray | None:
    """Gemiddeld (r, g, b) over het stuk clip dat een shot gebruikt, 0..1.

    Valt terug op de hele clip als er geen meting in het venster valt (een
    heel kort shot tussen twee meetmomenten).
    """
    reeks = clip.get("reeks") or {}
    tijden = np.asarray(reeks.get("tijden") or [], dtype=float)
    balans = np.asarray(reeks.get("balans") or [], dtype=float)
    if tijden.size == 0 or balans.shape[0] != tijden.size or balans.ndim != 2:
        return None
    masker = (tijden >= bron_start - 1e-6) & (tijden < bron_eind + 1e-6)
    stuk = balans[masker] if masker.any() else balans
    return stuk.mean(axis=0)


def versterking(bron: np.ndarray, doel: np.ndarray) -> dict[str, float]:
    """De versterking per kanaal die `bron` op `doel` brengt (in lineair licht).

    Twee stappen die samen één vermenigvuldiging zijn:
    1. helderheid: de luminantie van de bron naar die van het doel;
    2. grijsbalans: daarna elk kanaal naar dezelfde verhouding tot de
       luminantie als het doel heeft (grey-world).
    Geklemd, en afgerond op drie decimalen zodat de EDL leesbaar blijft.
    """
    b = _lin(bron)
    d = _lin(doel)
    w = np.array([0.2126, 0.7152, 0.0722])
    yb, yd = float(b @ w), float(d @ w)
    if yb < 1e-4 or yd < 1e-4:
        return {}
    helder = yd / yb
    # Kanaalverhouding t.o.v. de eigen luminantie, bron → doel.
    vb = b / yb
    vd = d / yd
    g = helder * np.where(vb > 1e-4, vd / np.maximum(vb, 1e-4), 1.0)
    # Van lineair terug naar codes: een factor in lineair licht is in codes
    # factor^(1/gamma). Zo vermenigvuldigen shader en ffmpeg de sRGB-codes.
    g = np.power(np.clip(g, 1e-3, None), 1.0 / GAMMA)
    g = np.clip(g, MIN_VERSTERKING, MAX_VERSTERKING)
    if np.all(np.abs(g - 1.0) < DREMPEL):
        return {}
    return {"r": round(float(g[0]), 3), "g": round(float(g[1]), 3), "b": round(float(g[2]), 3)}


def stem_af(edl: EDL, analyse: dict) -> int:
    """Zet `kleur` op elk shot van de EDL. Geeft het aantal afgestemde shots.

    Het doel is de mediaan van de shots (niet van de clips): wat vaak in beeld
    is bepaalt de toon. Een EDL zonder metingen (oude analyse) blijft
    onaangeroerd.
    """
    clips = {c["id"]: c for c in analyse.get("clips") or []}
    metingen: list[tuple[int, np.ndarray]] = []
    for i, b in enumerate(edl.video):
        clip = clips.get(b.clip)
        if not clip:
            continue
        m = gemiddelde_balans(clip, b.bron_start, b.bron_eind)
        if m is not None:
            metingen.append((i, m))
    if len(metingen) < 2:
        for b in edl.video:
            b.kleur = {}
        return 0
    doel = np.median(np.stack([m for _, m in metingen]), axis=0)
    n = 0
    gezet = set()
    for i, m in metingen:
        edl.video[i].kleur = versterking(m, doel)
        gezet.add(i)
        n += bool(edl.video[i].kleur)
    for i, b in enumerate(edl.video):
        if i not in gezet:
            b.kleur = {}
    return n


def filter_voor(kleur: dict[str, float]) -> str | None:
    """Het ffmpeg-filter voor deze versterking, of None bij de eenheid."""
    if not kleur:
        return None
    r, g, b = (float(kleur.get(k, 1.0)) for k in ("r", "g", "b"))
    if all(abs(x - 1.0) < 1e-3 for x in (r, g, b)):
        return None
    return f"colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f}"
