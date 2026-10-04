"""Staarten van overgangen: altijd precies zoveel frames als gevraagd.

De compositor leest `staarten.mp4` als één doorlopende stroom en pakt per
overgang `n` frames. Komt één staart frames tekort, dan eet hij de frames van
de volgende op: elke overgang daarna toont het verkeerde beeld, en bij
uitputting breekt de export af.

De drie manieren waarop een staart te kort werd:
- blok A eindigt op (of vlak voor) het einde van zijn bron — er valt niets
  meer door te lopen;
- blok A stond stil (`bevriezen`);
- `opties.tot` knipt de blokkenlijst in.
"""

from __future__ import annotations

import pytest
from cve import compositor, media, render as render_mod
from cve.edl import EDL, Afwerking, Canvas, Look, Overgang, VideoBlok

from test_rpc_looks import lookproject  # noqa: F401  (fixture)
from test_rpc_project import nodig_ffmpeg

FPS = 30
N = 24          # frames per blok
OVER = 12       # frames overgang
CLIP = 10.0     # lengte van de testclip in seconden


def _edl(project: str, starts: list[float], *, bevriezen: float = 0.0) -> EDL:
    edl = EDL(project=project, canvas=Canvas(breedte=640, hoogte=360, fps=FPS))
    edl.look = Look(id="geen", sterkte=0.0)
    edl.afwerking = Afwerking()
    edl.video = [
        VideoBlok(
            id=f"B{i + 1}", clip="C01", bestand="clip-1.mp4", bron_start=s,
            duur=N / FPS, tijdlijn_start=i * N / FPS, frames=N,
            vulmodus="vul", zoom="geen",
            bevriezen=bevriezen if i == 0 else 0.0,
            overgang_in=Overgang(soort="snede" if i == 0 else "crossfade",
                                 duur=0.0 if i == 0 else OVER / FPS),
        )
        for i, s in enumerate(starts)
    ]
    return edl


def _staartframes(project: str, pdir, edl: EDL) -> tuple[int, int]:
    """(geleverd, gevraagd) frames in staarten.mp4."""
    edl.schrijf(pdir / "edl.json")
    render_mod.render(
        project, opties=render_mod.RenderOpties(modus="preview", houd_tussenbestanden=True),
        log=lambda *_: None,
    )
    staarten = pdir / "cache" / "render-preview" / "staarten.mp4"
    assert staarten.exists(), "geen staarten gerenderd"
    gevraagd = OVER * sum(1 for b in edl.video if b.overgang_in.soort != "snede")
    return media.frames_in(staarten), gevraagd


@nodig_ffmpeg
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_staart_op_het_einde_van_de_bron_levert_toch_n_frames(lookproject):  # noqa: F811
    project, pdir, _ = lookproject
    # B1 eindigt precies op het bronnende: na de seek is er geen frame meer.
    edl = _edl(project, [CLIP - N / FPS, 1.0, 4.0])
    assert edl.video[0].bron_eind == CLIP
    assert _staartframes(project, pdir, edl) == (2 * OVER, 2 * OVER)


@nodig_ffmpeg
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_staart_vlak_voor_het_bronnende_levert_toch_n_frames(lookproject):  # noqa: F811
    project, pdir, _ = lookproject
    # Nog 0,1 s bron over voor een staart van 12 frames.
    edl = _edl(project, [CLIP - N / FPS - 0.1, 1.0, 4.0])
    assert _staartframes(project, pdir, edl) == (2 * OVER, 2 * OVER)


@nodig_ffmpeg
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_staart_na_bevriezen_levert_n_frames(lookproject):  # noqa: F811
    project, pdir, _ = lookproject
    edl = _edl(project, [1.0, 4.0, 7.0], bevriezen=0.4)
    assert _staartframes(project, pdir, edl) == (2 * OVER, 2 * OVER)


@nodig_ffmpeg
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_staarten_bij_opties_tot(lookproject):  # noqa: F811
    project, pdir, _ = lookproject
    edl = _edl(project, [CLIP - N / FPS, 1.0, 4.0])
    edl.schrijf(pdir / "edl.json")
    render_mod.render(
        project,
        opties=render_mod.RenderOpties(modus="preview", tot=2 * N / FPS,
                                       houd_tussenbestanden=True),
        log=lambda *_: None,
    )
    staarten = pdir / "cache" / "render-preview" / "staarten.mp4"
    # Twee blokken, dus één overgang.
    assert media.frames_in(staarten) == OVER
