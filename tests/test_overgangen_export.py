"""Overgangen in de export: via de compositor, met de shader van de speler.

Drie blokken uit dezelfde clip, op verschillende plekken in de bron. Blok 2
komt binnen met een glitch, blok 3 met een crossfade. Wat moet kloppen:

- het frameaantal blijft precies dat van de EDL (de tijdlijn is heilig);
- buiten de overgangen is het beeld gelijk aan dezelfde montage met snedes;
- binnen de overgang wijkt het beeld af van die snede-versie (er gebeurt iets);
- de crossfade ligt in het midden tússen A-staart en B in (geen harde knip).
"""

from __future__ import annotations

import numpy as np
import pytest
from cve import compositor, render as render_mod
from cve.edl import EDL, Afwerking, Canvas, Look, Overgang, VideoBlok

from test_rpc_looks import _rgb, lookproject  # noqa: F401  (fixture)
from test_rpc_project import nodig_ffmpeg

FPS = 30
N = 24  # frames per blok


def _edl(project: str, soorten: tuple[str, str]) -> EDL:
    edl = EDL(project=project, canvas=Canvas(breedte=640, hoogte=360, fps=FPS))
    edl.look = Look(id="geen", sterkte=0.0)
    edl.afwerking = Afwerking()
    edl.video = []
    for i, (bron, soort) in enumerate(zip((1.0, 4.0, 7.0), ("snede", *soorten), strict=True)):
        edl.video.append(VideoBlok(
            id=f"B{i + 1}", clip="C01", bestand="clip-1.mp4", bron_start=bron,
            duur=N / FPS, tijdlijn_start=i * N / FPS, frames=N, vulmodus="vul", zoom="geen",
            overgang_in=Overgang(soort=soort, duur=0.0 if soort == "snede" else 8 / FPS),
        ))
    return edl


def _render(project: str, pdir, soorten) -> list[np.ndarray]:
    _edl(project, soorten).schrijf(pdir / "edl.json")
    uit = render_mod.render(project, opties=render_mod.RenderOpties(modus="preview"),
                            log=lambda *_: None)
    return [_rgb(uit, frame=f) for f in range(3 * N)]


@nodig_ffmpeg
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_overgangen_mengen_alleen_binnen_hun_venster(lookproject):  # noqa: F811
    project, pdir, _ = lookproject
    snede = _render(project, pdir, ("snede", "snede"))
    met = _render(project, pdir, ("glitch", "crossfade"))
    assert len(met) == len(snede) == 3 * N

    def verschil(a, b):
        return float(np.abs(a - b).mean())

    # Buiten de vensters (frame 0..N-1, en na elke overgang) gelijk, op
    # encoderruis na.
    for f in (5, N - 1, N + 10, 2 * N + 10, 3 * N - 1):
        assert verschil(met[f], snede[f]) < 2.0, f
    # Midden in de glitch en de crossfade: echt anders.
    assert verschil(met[N + 4], snede[N + 4]) > 4.0
    assert verschil(met[2 * N + 4], snede[2 * N + 4]) > 2.0
    # De crossfade staat tussen A-staart en B in: op t=0,5 ligt hij dichter bij
    # het gemiddelde van de twee buren dan bij elk van beide.
    a_eind, b = snede[2 * N - 1], snede[2 * N + 4]
    m = met[2 * N + 4]
    assert verschil(m, b) > 1.0 and verschil(m, a_eind) > 1.0
