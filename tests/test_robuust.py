"""Het robuustheid-dozijn van 13-10-2026: dingen die bij het nalopen op 05-10
gezien zijn maar nog niet gerepareerd. Elk punt één test die rood was.

Zie historie/2026-10-13-nalooprond-professioneel.md.
"""

import json
import threading
import time

import pytest
from cve import export, ingest, paths, rpc
from cve import montage as montage_mod
from cve import projecten as projecten_mod

from test_rpc_project import _maak_clip, _vraag, losse_projectmap, opgevangen  # noqa: F401

nodig_ffmpeg = pytest.mark.skipif(
    not paths.heeft_ffmpeg(), reason="ffmpeg/ffprobe niet gevonden"
)


# -- a. één onleesbare video blokkeert niet het hele inlezen ------------------


@nodig_ffmpeg
def test_een_onleesbare_video_gaat_opzij_en_de_rest_wordt_ingelezen(
    losse_projectmap, opgevangen
):
    _vraag("project.maak", naam="kapot")
    bron = losse_projectmap / "camera"
    bron.mkdir()
    _maak_clip(bron / "goed.mp4")
    (bron / "kapot.mp4").write_bytes(b"\x00" * 4096)  # geen video, wel een .mp4
    _vraag("project.voegtoe", project="kapot", paden=[str(bron / "goed.mp4"), str(bron / "kapot.mp4")])

    # Vóór de ingest: de lijst toont de kapotte al als onleesbaar.
    vooraf = _vraag("project.clips", project="kapot")
    assert {c["naam"]: bool(c.get("fout")) for c in vooraf} == {"goed.mp4": False, "kapot.mp4": True}

    assert _vraag("project.verwerk", project="kapot", stijl="landschap") == {"gestart": True}
    grens = time.monotonic() + 180
    while time.monotonic() < grens and not any(
        r.get("gebeurtenis") in ("klaar", "fout") for r in opgevangen
    ):
        time.sleep(0.2)
    fouten = [r for r in opgevangen if r["gebeurtenis"] == "fout"]
    assert not fouten, fouten

    ing = json.loads((paths.PROJECTEN / "kapot" / "ingest.json").read_text())
    assert [c["bestand"] for c in ing["clips"]] == ["goed.mp4"]
    assert ing["overgeslagen"][0]["bestand"] == "kapot.mp4"
    assert ing["overgeslagen"][0]["fout"]

    clips = _vraag("project.clips", project="kapot")
    per_naam = {c["naam"]: c for c in clips}
    assert per_naam["goed.mp4"]["id"].startswith("C")
    assert per_naam["kapot.mp4"]["aan"] is False
    assert per_naam["kapot.mp4"]["id"] is None
    assert per_naam["kapot.mp4"]["fout"]


def test_alleen_onleesbare_videos_is_wel_een_fout(losse_projectmap):
    pdir = paths.PROJECTEN / "niets"
    (pdir / "bronnen").mkdir(parents=True)
    (pdir / "bronnen" / "a.mp4").write_bytes(b"x" * 100)
    with pytest.raises(RuntimeError, match="Geen van de videobestanden"):
        ingest.ingest("niets", log=lambda *_: None)


# -- b. kopiëren bij importeren gaat via een tijdelijke naam ------------------


def test_een_afgebroken_kopie_laat_geen_half_bestand_op_de_eindnaam(losse_projectmap, monkeypatch):
    _vraag("project.maak", naam="half")
    bron = losse_projectmap / "ergens" / "film.mp4"
    bron.parent.mkdir()
    bron.write_bytes(b"v" * 5000)

    import shutil

    def kapotte_kopie(src, dst, *a, **k):
        from pathlib import Path

        Path(dst).write_bytes(b"v" * 100)  # de helft, en dan valt de kabel eruit
        raise OSError("schijf vol")

    echte_kopie = shutil.copy2
    monkeypatch.setattr(shutil, "copy2", kapotte_kopie)
    with pytest.raises(OSError):
        projecten_mod.voeg_toe("half", [str(bron)])
    bronmap = paths.PROJECTEN / "half" / "bronnen"
    assert not (bronmap / "film.mp4").exists()
    assert not list(bronmap.glob(".*.deel")), "tijdelijk bestand blijft niet achter"

    monkeypatch.setattr(shutil, "copy2", echte_kopie)
    uit = projecten_mod.voeg_toe("half", [str(bron)])
    assert uit[0]["naam"] == "film.mp4" and uit[0]["bytes"] == 5000
    assert (bronmap / "film.mp4").read_bytes() == bron.read_bytes()


# -- c. analysis.json wordt atomair geschreven --------------------------------


def test_analysis_json_wordt_niet_via_write_text_geschreven():
    """Een lezer in een andere draad mag nooit een half bestand zien."""
    from inspect import getsource

    from cve import analyse

    bron = getsource(analyse.analyseer)
    assert '.deel' in bron and "replace(uit)" in bron
    assert 'uit.write_text' not in bron


# -- f. een uitgezette clip leidt tot een nieuwe regie ------------------------


def test_een_uitgezette_clip_die_in_de_montage_staat_vraagt_nieuwe_regie(losse_projectmap):
    from cve.edl import EDL, VideoBlok

    _vraag("project.maak", naam="uit")
    pdir = paths.PROJECTEN / "uit"
    edl = EDL(
        project="uit",
        video=[VideoBlok(id="v001", clip="C01", bestand="een.mp4", bron_start=0.0,
                         duur=1.0, tijdlijn_start=0.0)],
    )
    edl.brief = montage_mod.brief_van("reis", "16:9", None, "")
    edl.schrijf(pdir / "edl.json")
    vraag = dict(stijl="reis", vorm="16:9", duur=None, montage=edl.brief["montage"])

    assert montage_mod.regie_nodig("uit", **vraag) is False
    projecten_mod.zet_selectie("uit", "een.mp4", False)
    assert montage_mod.regie_nodig("uit", **vraag) is True
    projecten_mod.zet_selectie("uit", "een.mp4", True)
    assert montage_mod.regie_nodig("uit", **vraag) is False
    # Een uitgezette clip die niet in de montage zit verandert niets.
    projecten_mod.zet_selectie("uit", "ander.mp4", False)
    assert montage_mod.regie_nodig("uit", **vraag) is False


# -- k. encoders proberen gebeurt niet op de leeslus --------------------------


def test_warm_op_meet_in_een_eigen_draad_en_de_vraag_erna_wacht_niet_dubbel(monkeypatch):
    export._encoders.clear()
    tellers = {"metingen": 0}
    traag = threading.Event()

    def nep_meten(codec):
        tellers["metingen"] += 1
        traag.wait(2)
        export._encoders[codec] = None
        return None

    monkeypatch.setattr(export, "_encoder_meten", nep_meten)
    draad = export.warm_op()
    assert draad.name == "export-encoders" and draad.daemon
    traag.set()
    draad.join(5)
    assert tellers["metingen"] == len(export.CODECS)
    # Tweede keer: alles uit de cache, geen meting meer.
    export.beschikbare_codecs()
    assert tellers["metingen"] == len(export.CODECS)
    export._encoders.clear()


def test_rpc_draai_roept_warm_op():
    from inspect import getsource

    assert "warm_op()" in getsource(rpc.draai)
