"""Elke montagestijl hoort een voorbeeldtegel te hebben.

Dit is de poort die Koen bij fase 3 vroeg: een test die faalt zodra er een
stijl zonder voorbeeld is. Dat gebeurt vanzelf zodra er een vijftiende stijl
bij komt in `styles/montage/` — en dan staat er in stap 2 een kaart met een
leeg vak, wat precies de belofte breekt die de andere dertien doen.

De tegels zelf maak je met `cve stijlvoorbeelden`; ze staan in git omdat ze mee
moeten in de app-bundel (offline, geen download).
"""

from __future__ import annotations

import subprocess

import pytest

from cve import montagestijl, paths, stijlvoorbeelden as sv


def test_elke_montagestijl_heeft_een_voorbeeld():
    mist = sv.ontbreekt()
    assert mist == [], (
        f"geen voorbeeldtegel voor: {', '.join(mist)}. "
        f"Draai `.venv/bin/cve stijlvoorbeelden` en commit "
        f"{sv.doelmap().relative_to(paths.ROOT)}/."
    )


def test_er_staan_geen_tegels_te_veel():
    """Een stijl die verdwijnt laat anders een tegel achter die niemand meer ziet."""
    bekend = set(montagestijl.ORDE)
    gevonden = {q.stem for q in sv.doelmap().glob("*.mp4")}
    assert gevonden - bekend == set(), f"tegel zonder montagestijl: {gevonden - bekend}"


def test_de_lijst_van_montagestijlen_klopt_met_de_bestanden():
    """`ORDE` is met de hand bijgehouden; dit vangt een stijl die er wel staat
    maar nergens genoemd wordt."""
    op_schijf = {q.stem for q in (paths.STYLES / "montage").glob("*.md")}
    assert op_schijf == set(montagestijl.ORDE), (
        f"alleen op schijf: {op_schijf - set(montagestijl.ORDE)}; "
        f"alleen in ORDE: {set(montagestijl.ORDE) - op_schijf}"
    )


@pytest.mark.skipif(not paths.heeft_ffmpeg(), reason="ffmpeg/ffprobe niet gevonden")
def test_de_tegels_zijn_klein_stil_en_van_de_juiste_lengte():
    """Een tegel die te groot of te lang is, is geen tegel meer.

    Ook: geen geluidsspoor. Veertien tegels die bij het aanwijzen geluid
    maken is precies het soort interface waar mensen hun geluid voor uitzetten.
    """
    for stijl in montagestijl.ORDE:
        pad = sv.doelmap() / f"{stijl}.mp4"
        uit = subprocess.run(
            [
                str(paths.ffprobe()), "-v", "error",
                "-show_entries", "stream=codec_type,width",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1",
                str(pad),
            ],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        regels = dict(
            r.split("=", 1) for r in uit.strip().splitlines() if "=" in r
        )
        assert "audio" not in uit, f"{stijl}: heeft een geluidsspoor"
        assert int(regels["width"]) == sv.BREEDTE, f"{stijl}: {regels['width']} px breed"
        # Koens kader is 3 tot 5 seconden. Alle tegels even lang, want een
        # lijst waarin de ene tegel twee keer zo lang doorloopt als de andere
        # suggereert een verschil dat er niet is.
        duur = float(regels["duration"])
        assert 3.0 <= duur <= 5.0, f"{stijl}: {duur:.1f} s"
        assert abs(duur - sv.DUUR) < 0.5, f"{stijl}: {duur:.1f} s, verwacht {sv.DUUR}"
        mb = pad.stat().st_size / 1024 / 1024
        assert mb < 1.0, f"{stijl}: {mb:.2f} MB — te groot voor een tegel"


def test_er_hoort_een_poster_bij_elke_tegel():
    """Zonder poster is de kaart een zwart vak tot de film geladen is, en met
    `preload="none"` gebeurt dat pas als je hem aanwijst."""
    for stijl in montagestijl.ORDE:
        jpg = sv.doelmap() / f"{stijl}.jpg"
        assert jpg.exists() and jpg.stat().st_size > 2000, f"{stijl}: geen bruikbare poster"


def test_het_bronmateriaal_is_van_onszelf():
    """Geen bestand van buiten in de recepten.

    De tegels gaan mee in een installer die uitgedeeld wordt. Alles wat erin
    zit moet door ffmpeg zelf gemaakt zijn — een `-i <bestand>` of een pad in
    een recept zou betekenen dat er materiaal van iemand anders in kan lekken.
    """
    for bron in sv._bronnen():
        assert bron.bron.startswith("mandelbrot="), bron.bron
        assert "/" not in bron.bron, bron.bron
        assert "file=" not in bron.kleur, bron.kleur
