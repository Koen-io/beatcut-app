"""Monteren in stap 4: verplaatsen, trimmen, splitsen, verwijderen, ongedaan.

Eén bewering loopt door alles heen: **na elke handeling ligt elke snede nog
op een tel**, en de montage is even lang als ervoor. Dat is de belofte van
BeatCut; een editor die hem breekt is een gewone editor.

Het project is dat van `test_rpc_bijwerken`: drie clips, 120 BPM, één shot
per maat.
"""

import pytest
from cve import monteren, paths

from test_rpc_bijwerken import gemonteerd  # noqa: F401
from test_rpc_montage import montageproject, opgevangen  # noqa: F401
from test_rpc_project import _vraag, nodig_ffmpeg


def _op_de_tel(m):
    frame = 1.0 / m["fps"]
    for s in m["shots"]:
        assert s["tel"] is not None, s
        assert abs(s["tel_afwijking"]) <= frame + 1e-3, s
    # Naadloos: elk shot begint waar het vorige eindigt.
    for a, b in zip(m["shots"], m["shots"][1:], strict=False):
        assert b["start"] == pytest.approx(a["start"] + a["duur"], abs=1e-4), (a, b)


def _inhoud(m):
    return [(s["clip"], round(s["bron_in"], 2)) for s in m["shots"]]


@nodig_ffmpeg
def test_verplaatsen_schuift_de_inhoud_niet_de_vakken(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    assert len(voor["shots"]) >= 3
    vakken = [(s["start"], s["duur"]) for s in voor["shots"]]
    inhoud = _inhoud(voor)

    na = _vraag("project.shot.verplaats", project=project, shot=voor["shots"][0]["id"], naar=2)
    assert [(s["start"], s["duur"]) for s in na["shots"]] == vakken
    verwacht = inhoud[1:3] + inhoud[:1] + inhoud[3:]
    assert [c for c, _ in _inhoud(na)] == [c for c, _ in verwacht]
    assert all(s["vast"] for s in na["shots"][:3])
    assert len({s["id"] for s in na["shots"]}) == len(na["shots"])
    _op_de_tel(na)


@nodig_ffmpeg
def test_trimmen_verschuift_een_snede_een_tel_en_de_lengte_blijft(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    a, b = voor["shots"][0], voor["shots"][1]
    tel = 60.0 / voor["bpm"]

    na = _vraag("project.shot.trim", project=project, shot=a["id"], kant="eind", tellen=1)
    a2, b2 = na["shots"][0], na["shots"][1]
    assert a2["duur"] == pytest.approx(a["duur"] + tel, abs=0.05)
    assert b2["duur"] == pytest.approx(b["duur"] - tel, abs=0.05)
    # Het rechter shot leverde zijn begin in: zijn bron begint later.
    assert b2["bron_in"] == pytest.approx(b["bron_in"] + tel * b["snelheid"], abs=0.05)
    assert na["duur"] == pytest.approx(voor["duur"], abs=1e-3)
    _op_de_tel(na)

    # En terug, via de andere kant van het tweede shot.
    terug = _vraag("project.shot.trim", project=project, shot=b2["id"], kant="begin", tellen=-1)
    assert terug["shots"][0]["duur"] == pytest.approx(a["duur"], abs=0.05)


@nodig_ffmpeg
def test_trimmen_weigert_de_buitenkant_en_een_te_kort_shot(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    m = _vraag("project.montage", project=project)
    eerste, laatste = m["shots"][0], m["shots"][-1]
    with pytest.raises(ValueError, match="ligt geen ander shot"):
        monteren.trim(project, eerste["id"], "begin", 1)
    with pytest.raises(ValueError, match="ligt geen ander shot"):
        monteren.trim(project, laatste["id"], "eind", 1)
    with pytest.raises(ValueError, match="kwart seconde"):
        # Het hele shot inleveren: er blijft niets van over.
        monteren.trim(project, eerste["id"], "eind", -eerste["tellen"])


@nodig_ffmpeg
def test_splitsen_knipt_op_een_tel_en_de_bron_loopt_door(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    shot = voor["shots"][0]
    assert shot["tellen"] >= 2, "fixture moet een shot van minstens twee tellen hebben"

    na = _vraag("project.shot.splits", project=project, shot=shot["id"])
    assert len(na["shots"]) == len(voor["shots"]) + 1
    a, b = na["shots"][0], na["shots"][1]
    assert a["clip"] == b["clip"] == shot["clip"]
    assert a["duur"] + b["duur"] == pytest.approx(shot["duur"], abs=1e-3)
    assert b["bron_in"] == pytest.approx(a["bron_in"] + a["duur"] * a["snelheid"], abs=0.05)
    assert b["overgang"] == "snede"
    assert na["duur"] == pytest.approx(voor["duur"], abs=1e-3)
    _op_de_tel(na)


@nodig_ffmpeg
def test_verwijderen_laat_de_buurman_het_vak_overnemen(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    n = len(voor["shots"])

    midden = voor["shots"][1]
    na = _vraag("project.shot.verwijder", project=project, shot=midden["id"])
    assert len(na["shots"]) == n - 1
    assert midden["id"] not in {s["id"] for s in na["shots"]}
    assert na["shots"][0]["duur"] == pytest.approx(
        voor["shots"][0]["duur"] + midden["duur"], abs=1e-3
    )
    assert na["duur"] == pytest.approx(voor["duur"], abs=1e-3)
    _op_de_tel(na)

    # Het eerste shot weg: het volgende schuift naar 0 en begint eerder in de bron.
    na2 = _vraag("project.shot.verwijder", project=project, shot=na["shots"][0]["id"])
    assert na2["shots"][0]["start"] == pytest.approx(0.0, abs=1e-3)
    _op_de_tel(na2)


@nodig_ffmpeg
def test_ongedaan_en_opnieuw_lopen_heen_en_terug(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    begin = _vraag("project.montage", project=project)
    stand0 = begin["geschiedenis"]

    een = _vraag("project.shot.splits", project=project, shot=begin["shots"][0]["id"])
    twee = _vraag("project.shot.verwijder", project=project, shot=een["shots"][-1]["id"])
    assert twee["geschiedenis"]["terug"] == stand0["terug"] + 2
    assert twee["geschiedenis"]["vooruit"] == 0

    terug1 = _vraag("project.ongedaan", project=project)
    assert _inhoud(terug1) == _inhoud(een)
    terug2 = _vraag("project.ongedaan", project=project)
    assert _inhoud(terug2) == _inhoud(begin)
    assert terug2["geschiedenis"]["vooruit"] == 2

    vooruit = _vraag("project.opnieuw", project=project)
    assert _inhoud(vooruit) == _inhoud(een)

    # Een nieuwe wijziging maakt de vooruit-stapel leeg.
    nieuw = _vraag("project.shot.trim", project=project, shot=vooruit["shots"][0]["id"],
                   kant="eind", tellen=1)
    assert nieuw["geschiedenis"]["vooruit"] == 0


@nodig_ffmpeg
def test_shot_zet_en_opnieuw_regisseren_zijn_ook_terug_te_draaien(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    _vraag("project.shot.zet", project=project, shot=voor["shots"][0]["id"], snelheid=0.5)
    terug = _vraag("project.ongedaan", project=project)
    assert terug["shots"][0]["snelheid"] == voor["shots"][0]["snelheid"]


def test_niets_ongedaan_te_maken_is_een_nette_fout(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    (tmp_path / "leeg").mkdir()
    with pytest.raises(ValueError, match="niets om ongedaan"):
        monteren.ongedaan("leeg")
    assert monteren.stand("leeg") == {"terug": 0, "vooruit": 0}


def test_de_geschiedenis_houdt_er_vijftig(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    pdir = tmp_path / "p"
    pdir.mkdir()
    (pdir / "edl.json").write_text("{}")
    for _ in range(monteren.MAX_STAPPEN + 7):
        monteren.bewaar_stap(pdir)
    assert monteren.stand("p")["terug"] == monteren.MAX_STAPPEN
