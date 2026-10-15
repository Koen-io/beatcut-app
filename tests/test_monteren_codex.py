"""De drie bevindingen uit de Codex-tegenlezing van `monteren.py` (14-10-2026).

Elk met de reproductie die Codex gaf, op een kunstmatig project zonder
ffmpeg: tellen om de halve seconde, clips van 30 s.
"""

import json
from pathlib import Path

import pytest
from cve import monteren, paths
from cve.edl import EDL, AudioSpoor, VideoBlok


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    monkeypatch.setattr(monteren, "_uit", lambda p: EDL.lees(tmp_path / p / "edl.json"))
    pdir = tmp_path / "p"
    pdir.mkdir()
    tellen = [round(i * 0.5, 3) for i in range(80)]
    (pdir / "analysis.json").write_text(json.dumps({
        "muziek": {"beats": tellen, "maten": tellen[::4], "bpm": 120},
        "clips": [{"id": "C01", "reeks": {}}, {"id": "C02", "reeks": {}}],
    }))
    (pdir / "ingest.json").write_text(json.dumps({"clips": [
        {"id": "C01", "duur": 30.0}, {"id": "C02", "duur": 30.0},
    ]}))
    return pdir


def _schrijf(pdir: Path, *blokken: VideoBlok) -> None:
    edl = EDL(project="p", video=list(blokken))
    edl.canvas.fps = 30
    edl.audio = [AudioSpoor(bestand="m.wav", bron_start=0.0, duur=edl.duur)]
    edl.op_framerooster()
    edl.schrijf(pdir / "edl.json")


def _blok(i, clip, start, duur, **kw):
    return VideoBlok(id=f"v{i}", clip=clip, bestand=f"{clip}.mp4", tijdlijn_start=start, duur=duur, **kw)


def test_trim_met_ramp_houdt_het_einde_van_de_bron_vast(project):
    """Codex 1: rechter shot 4 s, bron 10, ramp 1×→3×; begin een tel naar rechts."""
    ramp = [{"t": 0.0, "snelheid": 1.0}, {"t": 1.0, "snelheid": 3.0}]
    _schrijf(project,
             _blok(1, "C01", 0.0, 2.0, bron_start=0.0),
             _blok(2, "C02", 2.0, 4.0, bron_start=10.0, snelheid_verloop=ramp))
    voor = EDL.lees(project / "edl.json").video[1]
    eind_voor = voor.bron_start + voor.bron_lengte
    assert eind_voor == pytest.approx(18.0, abs=0.01)

    na = monteren.trim("p", "v2", "begin", 1).video[1]
    assert na.duur == pytest.approx(3.5, abs=1e-3)
    assert na.snelheid_verloop, "de ramp blijft een ramp"
    assert na.bron_start + na.bron_lengte == pytest.approx(eind_voor, abs=0.01)


def test_splitsen_in_de_bevroren_staart_houdt_hetzelfde_beeld(project):
    """Codex 2: shot 4 s, bron 0, 1×, laatste 2 s bevroren; knip op 3 s."""
    _schrijf(project,
             _blok(1, "C01", 0.0, 4.0, bron_start=0.0, bevriezen=2.0),
             _blok(2, "C02", 4.0, 2.0, bron_start=0.0))
    uit = monteren.splits("p", "v1", op=3.0).video
    eerste, tweede = uit[0], uit[1]
    assert eerste.duur == pytest.approx(3.0, abs=1e-3)
    # Het eerste deel beweegt nog steeds 2 s en staat dan 1 s stil.
    assert eerste.duur - eerste.bevriezen == pytest.approx(2.0, abs=0.05)
    # Het tweede deel is het stilstaande eindbeeld: bron rond 2 s, niet 3 s.
    assert tweede.bron_start == pytest.approx(2.0 - 1 / 30, abs=0.01)
    assert tweede.duur - tweede.bevriezen <= 0.05
    # En het knippen in het bewegende deel werkt zoals voorheen.
    _schrijf(project,
             _blok(1, "C01", 0.0, 4.0, bron_start=0.0, bevriezen=2.0),
             _blok(2, "C02", 4.0, 2.0, bron_start=0.0))
    uit = monteren.splits("p", "v1", op=1.0).video
    assert uit[0].bevriezen == 0.0 and uit[0].duur == pytest.approx(1.0, abs=1e-3)
    assert uit[1].bron_start == pytest.approx(1.0, abs=0.01)
    assert uit[1].bevriezen == pytest.approx(2.0, abs=0.05)


def test_een_mislukte_wijziging_laat_redo_en_terug_staan(project, monkeypatch):
    """Codex 3: B ongedaan naar A, dan faalt een trim bij het schrijven."""
    _schrijf(project,
             _blok(1, "C01", 0.0, 2.0, bron_start=0.0),
             _blok(2, "C02", 2.0, 2.0, bron_start=0.0))
    monteren.trim("p", "v1", "eind", 1)      # B
    monteren.ongedaan("p")                    # terug naar A
    stand = monteren.stand("p")
    assert stand == {"terug": 0, "vooruit": 1}

    def kapot(self, pad):
        raise OSError("schijf vol")

    # Alleen hier: `monkeypatch.undo()` zou ook PROJECTEN terugzetten.
    with monkeypatch.context() as m:
        m.setattr(EDL, "schrijf", kapot)
        with pytest.raises(OSError):
            monteren.trim("p", "v1", "eind", 1)
    assert monteren.stand("p") == stand, "redo en terug-stapel onaangetast"
    # En redo werkt nog.
    na = monteren.opnieuw("p")
    assert na.video[0].duur == pytest.approx(2.5, abs=1e-3)


def test_een_mislukt_ongedaan_laat_de_stapels_staan(project, monkeypatch):
    _schrijf(project,
             _blok(1, "C01", 0.0, 2.0, bron_start=0.0),
             _blok(2, "C02", 2.0, 2.0, bron_start=0.0))
    monteren.trim("p", "v1", "eind", 1)
    stand = monteren.stand("p")
    with monkeypatch.context() as m:
        m.setattr(EDL, "schrijf", lambda self, pad: (_ for _ in ()).throw(OSError("vol")))
        with pytest.raises(OSError):
            monteren.ongedaan("p")
    assert monteren.stand("p") == stand
