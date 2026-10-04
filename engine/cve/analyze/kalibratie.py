"""Alle ijkpunten van de beeldanalyse op een plek.

Waarom hier: de ruwe metingen (Laplaciaan-variantie, optical-flow-magnitude)
hebben geen betekenis op zichzelf. Ze moeten vertaald worden naar 0..1 met
ankers die op echt materiaal zijn gemeten. Die ankers horen zichtbaar en
aanpasbaar te zijn, niet verstopt in een formule.

Gemeten op 21 iPhone-clips (4K60 HEVC, proxy 540p30), 11 augustus 2026:

    Laplaciaan-variantie  mediaan per clip:  631 .. 8366  (mediaan 3418)
    optical-flow-magnitude mediaan per clip: 0.29 .. 9.28 (mediaan 5.31)
    grijswaarde-std       mediaan per clip:  50   .. 71

Bij ander bronmateriaal (drone, GoPro, camera met andere ruis) kunnen deze
ankers verschuiven. Draai `cve ijk <project>` om ze opnieuw te meten.
"""

from __future__ import annotations

import math

# --- Scherpte -------------------------------------------------------------
# Laplaciaan-variantie is grofweg logaritmisch verdeeld. We ankeren op
# log10: alles onder ONSCHERP telt als onbruikbaar, alles boven SCHERP als top.
SCHERPTE_ONSCHERP = 250.0  # log10 = 2.40
SCHERPTE_SCHERP = 6500.0  # log10 = 3.81

# --- Beweging -------------------------------------------------------------
# Gemiddelde flow-magnitude in pixels per meting, op 320px breed.
BEWEGING_STIL = 0.15
BEWEGING_VOL = 11.0

# --- Shake ----------------------------------------------------------------
# Verandering van bewegingssnelheid tussen opeenvolgende metingen.
SHAKE_RUSTIG = 0.15
SHAKE_WILD = 3.0

# --- Vlakheid -------------------------------------------------------------
# Standaardafwijking van grijswaarden: laag = weinig detail (lucht, muur).
DETAIL_LEEG = 18.0
DETAIL_RIJK = 70.0

# --- Belichting -----------------------------------------------------------
BELICHTING_DOEL = 0.45  # gewenste gemiddelde helderheid (0..1)
BELICHTING_MARGE = 0.45  # hoever mag het afwijken voor het naar 0 zakt
CLIPPING_STRAF = 3.0  # hoe zwaar uitgebrande/dichtgelopen pixels tellen


def _lineair(waarde: float, laag: float, hoog: float) -> float:
    """Schaal waarde van [laag, hoog] naar [0, 1] en knip af."""
    if hoog <= laag:
        return 0.0
    return float(min(1.0, max(0.0, (waarde - laag) / (hoog - laag))))


def scherpte(laplaciaan_variantie: float) -> float:
    """Laplaciaan-variantie -> 0..1. Logaritmisch, want zo is de spreiding."""
    if laplaciaan_variantie <= 0:
        return 0.0
    return _lineair(
        math.log10(laplaciaan_variantie),
        math.log10(SCHERPTE_ONSCHERP),
        math.log10(SCHERPTE_SCHERP),
    )


def beweging(flow_magnitude: float) -> float:
    return _lineair(flow_magnitude, BEWEGING_STIL, BEWEGING_VOL)


def shake(flow_verandering: float) -> float:
    return _lineair(flow_verandering, SHAKE_RUSTIG, SHAKE_WILD)


def vlakheid(grijs_std: float) -> float:
    """1.0 = leeg beeld zonder detail, 0.0 = rijk gedetailleerd."""
    return 1.0 - _lineair(grijs_std, DETAIL_LEEG, DETAIL_RIJK)
