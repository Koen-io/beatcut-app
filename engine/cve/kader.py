"""Herkaderen - waar valt het venster in de bron?

Een liggende clip in een staand canvas (9:16, 4:5) past niet. Tot nu toe
kwamen er wazige balken om heen, of werd het midden weggesneden - en het
onderwerp staat zelden precies in het midden. Dit bestand rekent uit waar het
venster dan wél hoort te staan.

Er zijn twee stappen, en ze staan in deze volgorde ook in de renderer en in de
speler:

  1. **het kader** - een venster op canvasverhouding, geschoven naar het
     aandachtspunt en geklemd binnen de bron;
  2. **Ken Burns** - zoomen en schuiven *binnen* dat venster.

De getallen zijn fracties van de bron (0..1), niet pixels. Daardoor rekenen de
renderer (ffmpeg `crop`, in `iw`/`ih`) en de speler (uv's in de shader) met
precies dezelfde formule. `app/src/speler/uniforms.ts` heeft dezelfde drie
functies; `tests/test_kader.py` legt beide tegen één tabel getallen aan.
"""

from __future__ import annotations

MIDDEN = 0.5


def venster(bronverhouding: float, canvasverhouding: float, zoom: float = 1.0) -> tuple[float, float]:
    """Breedte en hoogte van het zichtbare venster, als fractie van de bron.

    Nooit groter dan 1: buiten de bron samplen geeft een gespiegelde rand.
    """
    z = max(1e-4, zoom)
    b = h = 1.0 / z
    if bronverhouding > canvasverhouding:
        b *= canvasverhouding / bronverhouding
    else:
        h *= bronverhouding / canvasverhouding
    return b, h


def schuif(venster: float, punt: float) -> float:
    """De linker- of bovenrand van het venster, zodat `punt` het midden is.

    Geklemd binnen de bron: een onderwerp vlak aan de rand trekt het venster
    niet buiten het beeld, het komt dan uit het midden te staan.
    """
    ruimte = max(0.0, 1.0 - venster)
    return min(ruimte, max(0.0, punt - venster / 2.0))


def punt_op(kader: dict | None, f: float = 0.0) -> tuple[float, float]:
    """Het aandachtspunt van een blok op fractie `f` (0..1) van zijn duur.

    Drie vormen, alle drie geldig in `edl.json`:
      {}                              -> het midden (geen kader gezet)
      {"x": .., "y": ..}              -> één vast punt
      {"punten": [{"t", "x", "y"}..]} -> lineair tussen de keyframes
    """
    if not kader:
        return MIDDEN, MIDDEN
    punten = kader.get("punten") or []
    if not punten:
        return float(kader.get("x", MIDDEN)), float(kader.get("y", MIDDEN))

    f = min(1.0, max(0.0, f))
    rij = [(float(p["t"]), float(p.get("x", MIDDEN)), float(p.get("y", MIDDEN))) for p in punten]
    if f <= rij[0][0]:
        return rij[0][1], rij[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(rij, rij[1:]):
        if f <= t1:
            if t1 <= t0:
                return x0, y0
            deel = (f - t0) / (t1 - t0)
            return x0 + (x1 - x0) * deel, y0 + (y1 - y0) * deel
    return rij[-1][1], rij[-1][2]


def beweegt(kader: dict | None) -> bool:
    """Staat dit kader stil, of loopt het over keyframes?"""
    return bool(kader and kader.get("punten"))


# --------------------------------------------------------------------------
# Het aandachtspunt uit de analyse halen
# --------------------------------------------------------------------------


def bronverhouding(clip: dict) -> float:
    """De verhouding zoals je de clip ziet, dus na rotatie.

    `breedte` en `hoogte` in `ingest.json` zijn de getallen uit het bestand;
    een iPhone-opname die je rechtop hield staat daar als 3840x2160 met een
    rotatievlag. `verticaal` is wél al gedraaid - dus daar lijnen we op uit.
    """
    b, h = float(clip.get("breedte") or 16), float(clip.get("hoogte") or 9)
    if b <= 0 or h <= 0:
        return 16 / 9
    if bool(clip.get("verticaal")) != (h > b):
        b, h = h, b
    return b / h


def uit_reeks(reeks: dict, start: float, eind: float) -> tuple[float, float, float, float]:
    """Het aandachtspunt over een stuk clip, plus hoeveel het heen en weer gaat.

    Geeft (x, y, spreiding_x, spreiding_y). De spreiding is het verschil
    tussen het laagste en het hoogste punt in dit venster: hoe ver het
    onderwerp door het beeld loopt. Daarmee beslist de regisseur of
    wegsnijden kan of dat het een wazige achtergrond moet worden.
    """
    tijden = reeks.get("tijden") or []
    xs = reeks.get("aandacht_x") or []
    ys = reeks.get("aandacht_y") or []
    if not tijden or not xs or not ys:
        return MIDDEN, MIDDEN, 0.0, 0.0

    n = min(len(tijden), len(xs), len(ys))
    binnen = [i for i in range(n) if start - 1e-6 <= tijden[i] <= eind + 1e-6]
    if not binnen:
        # Korter dan één meetmoment: pak de dichtstbijzijnde meting.
        midden = (start + eind) / 2.0
        binnen = [min(range(n), key=lambda i: abs(tijden[i] - midden))]

    kx = [float(xs[i]) for i in binnen]
    ky = [float(ys[i]) for i in binnen]
    return (
        round(sum(kx) / len(kx), 4),
        round(sum(ky) / len(ky), 4),
        round(max(kx) - min(kx), 4),
        round(max(ky) - min(ky), 4),
    )


# Hoeveel van het venster het onderwerp mag beslaan voordat wegsnijden niet
# meer kan. 0,7 laat een onderwerp dat over tweederde van het venster
# beweegt nog toe; loopt het verder, dan valt het er onderweg uit en is een
# wazige achtergrond eerlijker dan een halve rug in beeld.
PAST_MARGE = 0.7


def past(spreiding: float, venster: float) -> bool:
    """Blijft het onderwerp binnen één vast venster van deze breedte?"""
    return spreiding <= venster * PAST_MARGE


# Onder dit verschil in verhouding valt er niets te herkaderen: 16:9 in 16:9
# of 4:5 in 1:1 scheelt zo weinig dat schuiven geen zichtbare ruimte heeft.
MINIMAAL_VERSCHIL = 0.02


def as_met_ruimte(bronverhouding: float, canvasverhouding: float) -> str | None:
    """Op welke as valt er te herkaderen? "x", "y", of None als het past.

    De interface gebruikt dit om de knoppen te kiezen: links/midden/rechts bij
    een liggende clip in een staand canvas, boven/midden/onder andersom.
    """
    b, h = venster(bronverhouding, canvasverhouding)
    if b < 1.0 - MINIMAAL_VERSCHIL:
        return "x"
    if h < 1.0 - MINIMAAL_VERSCHIL:
        return "y"
    return None


def kies(
    clip: dict, canvasverhouding: float, reeks: dict, start: float, eind: float
) -> tuple[str, dict]:
    """Vulmodus plus kader voor een stuk clip op dit canvas.

    Drie uitkomsten:

      ("vul", {})            de clip past al op het canvas, niets te kiezen;
      ("vul", {"x", "y"})    wegsnijden rond het onderwerp - het blijft binnen
                             één venster, dus het beeld vult het hele canvas;
      ("wazig", {})          het onderwerp loopt te ver door het beeld. Dan
                             zou wegsnijden het onderweg afsnijden, en is een
                             wazige achtergrond eerlijker.

    Zonder gemeten aandachtspunten (een `analysis.json` van vóór dit veld)
    blijft het bij "wazig": dat was het altijd, en een kader verzinnen op
    gegevens die er niet zijn is erger dan niets doen.
    """
    bv = bronverhouding(clip)
    as_ = as_met_ruimte(bv, canvasverhouding)
    if as_ is None:
        return "vul", {}
    if not (reeks.get("aandacht_x") and reeks.get("aandacht_y")):
        return "wazig", {}

    b, h = venster(bv, canvasverhouding)
    x, y, spreiding_x, spreiding_y = uit_reeks(reeks, start, eind)
    spreiding, breed = (spreiding_x, b) if as_ == "x" else (spreiding_y, h)
    if not past(spreiding, breed):
        return "wazig", {}
    return "vul", {"x": x, "y": y}
