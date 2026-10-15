"""De geleide route (Stijl → Look → Bijwerken) en de export aan het eind.

1. `project.voorbereid` bedenkt de montage zonder te renderen, en doet dat
   alleen opnieuw als de keuzes uit Stijl veranderd zijn — anders gooit heen
   en weer lopen het handwerk uit Bijwerken weg;
2. een export met een eigen keuze levert naast de master het gevraagde
   bestand, en meldt waar het staat;
3. een map die niet bestaat hoor je vóór de render, niet erna.
"""

from pathlib import Path

import pytest
from cve import media, paths

from test_rpc_montage import (  # noqa: F401 — fixtures komen hier vandaan
    _wacht_op_einde,
    _zet_muziek,
    montageproject,
    opgevangen,
)
from test_rpc_project import _vraag, nodig_ffmpeg

KEUZE = dict(stijl="reis", montage="cine", vorm="16:9", duur=8.0)


@nodig_ffmpeg
def test_voorbereid_regisseert_alleen_als_de_keuze_veranderd_is(montageproject):  # noqa: F811
    project, basis = montageproject
    _zet_muziek(project, basis)
    edl = paths.PROJECTEN / project / "edl.json"
    edl.unlink(missing_ok=True)

    eerste = _vraag("project.voorbereid", project=project, **KEUZE)
    assert eerste["opnieuw"] is True and eerste["uitleg"]
    m = _vraag("project.montage", project=project)
    assert m["shots"], "na voorbereiden hoort er een montage te liggen"

    # Handwerk: één shot op een andere snelheid.
    shot = m["shots"][0]
    _vraag("project.shot.zet", project=project, shot=shot["id"], snelheid=0.5)

    # Terug naar Stijl en weer verder met dezelfde keuze: niets opnieuw.
    tweede = _vraag("project.voorbereid", project=project, **KEUZE)
    assert tweede["opnieuw"] is False
    na = _vraag("project.montage", project=project)
    assert na["shots"][0]["snelheid"] == pytest.approx(0.5), "het handwerk is weggegooid"

    # Een andere vorm is een andere montage.
    derde = _vraag("project.voorbereid", project=project, **{**KEUZE, "vorm": "9:16"})
    assert derde["opnieuw"] is True


@nodig_ffmpeg
def test_een_export_met_eigen_keuze_levert_dat_bestand(montageproject, opgevangen, tmp_path):  # noqa: F811
    project, basis = montageproject
    _zet_muziek(project, basis)
    uitmap = tmp_path / "uit"
    uitmap.mkdir()
    opgevangen.clear()

    assert _vraag(
        "project.maakvideo", project=project, kwaliteit="eind", **KEUZE,
        export={"container": "mov", "resolutie": "540", "fps": "25", "audio_kbps": 128,
                "map": str(uitmap), "naam": "vakantie"},
    ) == {"gestart": True}
    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde
    data = einde["data"]

    # De master staat waar hij altijd stond, als mp4.
    master = Path(data["video"])
    assert master.suffix == ".mp4" and master.exists()
    # En de export staat waar het menu hem wilde.
    uit = data["export"]
    assert uit is not None and uit["omgezet"] is True
    pad = Path(uit["pad"])
    assert pad == uitmap / "vakantie.mov" and pad.stat().st_size == uit["bytes"]
    info = media.probe(pad)
    assert (info.breedte, info.hoogte) == (960, 540)
    assert info.fps == pytest.approx(25.0, abs=0.01)
    assert info.duur == pytest.approx(data["duur"], abs=0.2)

    stappen = [r["data"]["stap"] for r in opgevangen if r.get("gebeurtenis") == "voortgang"]
    assert "uitvoer" in stappen
    percentages = [r["data"]["percentage"] for r in opgevangen
                   if r.get("gebeurtenis") == "voortgang"]
    assert percentages == sorted(percentages), "de balk sprong terug"
    # De balk mag niet op 100 staan voordat het wegschrijven begint.
    voor_uitvoer = [r["data"]["percentage"] for r in opgevangen
                    if r.get("gebeurtenis") == "voortgang" and r["data"]["stap"] != "uitvoer"]
    assert max(voor_uitvoer) < 90

    # `project.video` blijft de master teruggeven, niet de export.
    assert Path(_vraag("project.video", project=project)["video"]) == master


@nodig_ffmpeg
def test_een_voorvertoning_trekt_zich_niets_aan_van_het_exportmenu(montageproject, opgevangen):  # noqa: F811
    project, basis = montageproject
    _zet_muziek(project, basis)
    opgevangen.clear()
    _vraag("project.maakvideo", project=project, kwaliteit="preview", **KEUZE,
           export={"container": "mov"})
    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde
    assert einde["data"]["export"] is None


def test_een_map_die_niet_bestaat_hoor_je_voor_de_render(montageproject, tmp_path):  # noqa: F811
    project, basis = montageproject
    _zet_muziek(project, basis)
    with pytest.raises(Exception, match="bestaat niet"):
        _vraag("project.maakvideo", project=project, kwaliteit="eind", **KEUZE,
               export={"map": str(tmp_path / "nergens")})
    # En het project is niet "bezig" achtergebleven.
    assert _vraag("bezig")["bezig"] is False


@nodig_ffmpeg
def test_andere_muziek_vraagt_een_nieuwe_regie(montageproject, tmp_path):  # noqa: F811
    # De brief (stijl, vorm, lengte) weet niets van de muziek. Zonder deze
    # controle bleef de montage op de tellen van het vorige nummer liggen, en
    # omdat dat bestand naar `_vorige/` verhuist, kwam de video er zonder
    # geluid uit.
    from cve import montage
    from test_rpc_montage import _maak_muziek

    project, basis = montageproject
    _zet_muziek(project, basis)
    (paths.PROJECTEN / project / "edl.json").unlink(missing_ok=True)
    _vraag("project.voorbereid", project=project, **KEUZE)
    assert montage.regie_nodig(project, stijl="reis", vorm="16:9", duur=8.0, montage="cine") is False

    ander = tmp_path / "ander-nummer.wav"
    _maak_muziek(ander)
    montage.zet_muziek(project, str(ander))
    montage.analyseer_muziek(project)
    assert montage.regie_nodig(project, stijl="reis", vorm="16:9", duur=8.0, montage="cine") is True
    # En de regie daarna legt het nieuwe nummer onder de montage.
    assert _vraag("project.voorbereid", project=project, **KEUZE)["opnieuw"] is True
    from cve.edl import EDL

    edl = EDL.lees(paths.PROJECTEN / project / "edl.json")
    assert edl.audio[0].bestand == "ander-nummer.wav"


@nodig_ffmpeg
def test_de_app_krijgt_de_keuzes_van_de_montage_die_er_ligt(montageproject):  # noqa: F811
    project, basis = montageproject
    _zet_muziek(project, basis)
    (paths.PROJECTEN / project / "edl.json").unlink(missing_ok=True)
    assert _vraag("project.stijlen", project=project)["brief"] is None
    _vraag("project.voorbereid", project=project, **{**KEUZE, "vorm": "9:16"})
    brief = _vraag("project.stijlen", project=project)["brief"]
    assert brief == {"stijl": "reis", "montage": "cine", "vorm": "9:16", "duur": 8.0}
