"""Speed-ramps: overal dezelfde bronlengte, en ffmpeg rendert ze echt."""
from __future__ import annotations

import subprocess

import pytest

from cve import montagestijl, paths, render
from cve.edl import VideoBlok, gemiddelde_snelheid, snelheid_op

RAMP = [{"t": 0.0, "snelheid": 1.0}, {"t": 0.5, "snelheid": 0.35}, {"t": 1.0, "snelheid": 2.2}]
VELOCITY = [{"t": 0.0, "snelheid": 1.0}, {"t": 0.5, "snelheid": 0.3}, {"t": 1.0, "snelheid": 2.5}]


def _blok(**kw) -> VideoBlok:
    return VideoBlok(id="v001", clip="C01", bestand="a.mp4", bron_start=0.0,
                     duur=2.0, tijdlijn_start=0.0, **kw)


def test_snelheid_op_is_lineair_tussen_de_punten():
    assert snelheid_op(RAMP, 0.0) == 1.0
    assert snelheid_op(RAMP, 0.25) == pytest.approx(0.675)
    assert snelheid_op(RAMP, 1.0) == 2.2


def test_bronlengte_volgt_het_verloop_en_de_regisseur_rekent_hetzelfde():
    b = _blok(snelheid_verloop=RAMP)
    assert b.bron_lengte == pytest.approx(2.0 * gemiddelde_snelheid(RAMP))
    assert b.bron_lengte == pytest.approx(2.0 * 0.975, abs=0.01)
    assert _blok(snelheid=2.0).bron_lengte == 4.0


def test_montagestijl_leest_de_ramp():
    st = montagestijl.laad("velocity", paths.STYLES if hasattr(paths, "STYLES") else paths.ROOT / "styles")
    if st.ramp:
        assert st.verloop()[0]["t"] == 0.0 and st.verloop()[-1]["t"] == 1.0


@pytest.mark.skipif(paths.ffmpeg() is None, reason="geen ffmpeg")
def test_ffmpeg_rendert_de_ramp_op_het_framerooster(tmp_path):
    # Bron die exact op bron_eind ophoudt (codex-review 03-10, #10): zonder
    # tpad gaf dit 119 frames.
    b = _blok(snelheid_verloop=VELOCITY)
    b.duur = 4.0
    doel = tmp_path / "uit.mp4"
    # Bron met een tijdstempel per frame; precies genoeg bron voor het blok.
    r = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-f", "lavfi",
         "-i", f"testsrc2=size=320x240:rate=30:duration={b.bron_lengte:.3f}",
         "-vf", f"setpts=PTS-STARTPTS,{render._rampfilter(b)},fps=30,tpad=stop_mode=clone:stop=3",
         "-frames:v", "120", "-c:v", "mpeg4", str(doel), "-y"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    n = subprocess.run(
        [str(paths.ffprobe()), "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(doel)],
        capture_output=True, text=True,
    ).stdout.strip()
    assert int(n) == 120


def test_brontijd_integreert_de_stukken_zoals_de_speler():
    """De brontijd midden in een ramp-shot — de som die `brontijdVan` in
    app/src/speler/demux.ts maakt, hier als referentie.

    Deze getallen staan ook in ontwerp/beatcut2/qa/speler-ronde3.js: daar
    wordt dezelfde som in de webview gedraaid en hiertegen gelegd. Zonder de
    stukken rekende de speler met een constante snelheid, en dan ligt het
    midden van een ramp-shot naast de beat.
    """
    b = _blok(snelheid_verloop=VELOCITY)
    stukken = b.snelheid_stukken()

    def brontijd(inBlok: float) -> float:
        over, bron = max(0.0, inBlok), 0.0
        for d, v in stukken:
            if over <= d:
                return b.bron_start + bron + over * v
            bron += d * v
            over -= d
        return b.bron_start + bron + over * stukken[-1][1]

    # Begin en eind: precies het bronvenster van het blok.
    assert brontijd(0.0) == pytest.approx(b.bron_start)
    assert brontijd(b.duur) == pytest.approx(b.bron_eind, abs=1e-6)
    # Het midden niet: de ramp zakt eerst naar 0,3x, dus daar is minder bron
    # opgemaakt dan de helft. Precies dit verschil zag de speler niet.
    half = brontijd(b.duur / 2)
    assert half < b.bron_start + b.bron_lengte / 2 - 0.1, half
    # En het loopt netjes op.
    reeks = [brontijd(b.duur * k / 20) for k in range(21)]
    assert reeks == sorted(reeks)
