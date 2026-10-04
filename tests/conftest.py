"""Wat voor élke test in deze map geldt.

Eén ding staat hier: het stijl-geheugen mag nooit in de werkmap van Koen
belanden. `geheugen.noteer()` schrijft naar `styles/geleerd/<stijl>.json` —
dat is de repo zelf, en een testrun hoort daar niets achter te laten. De
fixture stond eerst alleen in `test_rpc_bijwerken.py` en dekte dus alleen de
Bijwerken-tests; op 03-10-2026 stond er na een gewone run een verse
`styles/geleerd/reis.json` in de repo.
"""

import pytest
from cve import geheugen


@pytest.fixture(autouse=True)
def geleerd_naar_tmp(tmp_path, monkeypatch):
    """`styles/geleerd/` verhuist naar de tijdelijke map van deze test.

    `paths.STYLES` zelf mag niet verhuizen: de regisseur heeft de echte
    stijlbestanden nodig. Alleen de uitkomst gaat om.
    """
    doel = tmp_path / "geleerd"
    doel.mkdir(exist_ok=True)
    monkeypatch.setattr(geheugen, "geleerd_pad", lambda stijl: doel / f"{stijl}.json")


def pytest_sessionstart(session):
    """Bovenaan elke run: welke encoder en welke compositor-adapter hier gelden.

    Op een CI-runner is dat het eerste wat je wilt weten als iets anders
    uitvalt dan op de Mac (VideoToolbox in software, WARP, mpeg4-noodgreep).
    """
    try:
        from cve import compositor, media, paths

        enc = media.video_encoder()[0] if paths.heeft_ffmpeg() else "geen ffmpeg"
        comp = compositor.info() if compositor.binary() is not None else None
        adapter = f"{comp['adapter']} ({comp['backend']})" if comp else "geen compositor"
        regel = f"BeatCut: encoder {enc} · compositor {adapter}"
    except Exception as e:  # noqa: BLE001
        regel = f"BeatCut: omgeving onbekend ({e})"
    import sys

    print(regel, file=sys.stderr)
