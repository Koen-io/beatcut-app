"""Kleurafstemming tussen clips en stabilisatie (13-10-2026).

De wiskunde (`versterking`), de plek in de EDL (`stem_af`, `afstemmen`), de
ffmpeg-kant (`_kleurmatch_filter`, `deshake`), en één echte meting: een
donkere en een lichte clip komen na afstemming dichter bij elkaar, gemeten
in de gerenderde blokken.
"""

import json
import subprocess

import numpy as np
import pytest
from cve import kleurmatch, paths
from cve.edl import EDL, VideoBlok

from test_rpc_bijwerken import gemonteerd  # noqa: F401
from test_rpc_montage import montageproject, opgevangen  # noqa: F401
from test_rpc_project import _vraag, nodig_ffmpeg


def test_versterking_brengt_helderheid_en_balans_naar_het_doel():
    bron = np.array([0.42, 0.42, 0.50])  # wat donker en blauwig
    doel = np.array([0.50, 0.50, 0.50])  # neutraal grijs
    g = kleurmatch.versterking(bron, doel)
    assert g["r"] > 1.0 and g["g"] > 1.0
    assert g["b"] < g["r"], "blauw moet minder versterkt worden dan rood"
    # Toepassen op de bron (in codes) brengt hem dichtbij het doel.
    na = bron * np.array([g["r"], g["g"], g["b"]])
    assert np.abs(na - doel).max() < 0.03, na


def test_versterking_is_geklemd_en_laat_een_goed_shot_met_rust():
    assert kleurmatch.versterking(np.array([0.5, 0.5, 0.5]), np.array([0.5, 0.5, 0.5])) == {}
    assert kleurmatch.versterking(np.array([0.5, 0.5, 0.5]), np.array([0.505, 0.5, 0.5])) == {}
    g = kleurmatch.versterking(np.array([0.05, 0.05, 0.05]), np.array([0.9, 0.9, 0.9]))
    assert g == {"r": kleurmatch.MAX_VERSTERKING, "g": kleurmatch.MAX_VERSTERKING, "b": kleurmatch.MAX_VERSTERKING}
    assert kleurmatch.versterking(np.array([0.0, 0.0, 0.0]), np.array([0.5, 0.5, 0.5])) == {}


def _analyse(*balansen):
    return {
        "clips": [
            {"id": f"C0{i + 1}", "reeks": {"tijden": [0.0, 1.0, 2.0], "balans": [list(b)] * 3}}
            for i, b in enumerate(balansen)
        ]
    }


def _edl(*clips):
    return EDL(
        project="p",
        video=[VideoBlok(id=f"v{i}", clip=c, bestand=f"{c}.mp4", bron_start=0.0, duur=1.0,
                         tijdlijn_start=float(i)) for i, c in enumerate(clips)],
    )


def test_stem_af_zet_getallen_op_de_afwijkende_shots_en_niets_op_de_rest():
    analyse = _analyse([0.5, 0.5, 0.5], [0.5, 0.5, 0.5], [0.3, 0.3, 0.3])
    edl = _edl("C01", "C02", "C03")
    assert kleurmatch.stem_af(edl, analyse) == 1
    assert edl.video[0].kleur == {} and edl.video[1].kleur == {}
    assert edl.video[2].kleur["r"] > 1.1
    # Zonder metingen (oude analyse): niets, en geen fout.
    oud = _edl("C01", "C02")
    assert kleurmatch.stem_af(oud, {"clips": [{"id": "C01", "reeks": {}}]}) == 0
    assert all(b.kleur == {} for b in oud.video)
    # Eén shot: er is niets om op af te stemmen.
    assert kleurmatch.stem_af(_edl("C03"), analyse) == 0


def test_edl_bewaart_kleur_stabiliseer_en_afstemmen(tmp_path):
    edl = _edl("C01")
    edl.video[0].kleur = {"r": 1.1, "g": 1.0, "b": 0.9}
    edl.video[0].stabiliseer = True
    edl.afstemmen = False
    edl.schrijf(tmp_path / "edl.json")
    terug = EDL.lees(tmp_path / "edl.json")
    assert terug.video[0].kleur == {"r": 1.1, "g": 1.0, "b": 0.9}
    assert terug.video[0].stabiliseer is True and terug.afstemmen is False
    # Een EDL van vóór deze velden leest als: aan, zonder getallen.
    d = json.loads((tmp_path / "edl.json").read_text())
    del d["afstemmen"]
    for b in d["video"]:
        del b["kleur"], b["stabiliseer"]
    oud = EDL.van_dict(d)
    assert oud.afstemmen is True and oud.video[0].kleur == {} and oud.video[0].stabiliseer is False


def test_render_filter_volgt_de_schakelaar():
    from cve.render import _kleurmatch_filter, _stabilisatiefilter

    edl = _edl("C01")
    edl.video[0].kleur = {"r": 1.1, "g": 1.0, "b": 0.9}
    assert _kleurmatch_filter(edl.video[0], edl) == "colorchannelmixer=rr=1.100:gg=1.000:bb=0.900"
    edl.afstemmen = False
    assert _kleurmatch_filter(edl.video[0], edl) is None
    assert kleurmatch.filter_voor({}) is None and kleurmatch.filter_voor({"r": 1.0}) is None
    assert _stabilisatiefilter().startswith("deshake=")


@nodig_ffmpeg
def test_de_lgpl_ffmpeg_kent_beide_filters():
    uit = subprocess.run([str(paths.ffmpeg()), "-hide_banner", "-filters"], capture_output=True,
                         text=True, timeout=60).stdout
    assert " deshake " in uit and " colorchannelmixer " in uit


@nodig_ffmpeg
def test_via_rpc_afstemmen_en_stabiliseren_per_shot(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    m = _vraag("project.montage", project=project)
    assert m["afstemmen"] is True
    assert all("kleur" in s and "stabiliseer" in s for s in m["shots"])
    s0 = m["shots"][0]
    na = _vraag("project.shot.zet", project=project, shot=s0["id"], stabiliseer=True)
    assert na["shots"][0]["stabiliseer"] is True
    uit = _vraag("project.afstemmen", project=project, aan=False)
    assert uit["afstemmen"] is False
    assert _vraag("project.ongedaan", project=project)["afstemmen"] is True


@nodig_ffmpeg
def test_echte_meting_donker_en_licht_komen_bij_elkaar(tmp_path):
    """Twee clips, een donkere en een lichte; na afstemming via het
    ffmpeg-filter ligt het verschil in gemiddelde helderheid ruim lager."""
    import cv2

    f = str(paths.ffmpeg())

    def clip(naam, helderheid):
        p = tmp_path / naam
        subprocess.run([f, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"color=c=0x{helderheid:02x}{helderheid:02x}{helderheid:02x}:size=64x64:rate=10:duration=1",
                        "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", str(p)], check=True)
        return p

    def gemiddeld(p):
        cap = cv2.VideoCapture(str(p))
        ok, fr = cap.read()
        cap.release()
        assert ok
        return float(fr.mean()) / 255.0

    donker, licht = clip("donker.mp4", 0x50), clip("licht.mp4", 0x90)
    bal_d, bal_l = (np.full(3, gemiddeld(donker)), np.full(3, gemiddeld(licht)))
    doel = (bal_d + bal_l) / 2
    g_d, g_l = kleurmatch.versterking(bal_d, doel), kleurmatch.versterking(bal_l, doel)
    assert g_d and g_l

    def pas_toe(bron, g, naam):
        uitpad = tmp_path / naam
        subprocess.run([f, "-y", "-loglevel", "error", "-i", str(bron), "-vf",
                        kleurmatch.filter_voor(g), "-c:v", "mpeg4", "-q:v", "2", str(uitpad)], check=True)
        return gemiddeld(uitpad)

    na_d, na_l = pas_toe(donker, g_d, "d2.mp4"), pas_toe(licht, g_l, "l2.mp4")
    verschil_voor = abs(bal_l[0] - bal_d[0])
    verschil_na = abs(na_l - na_d)
    assert verschil_na < verschil_voor * 0.5, (verschil_voor, verschil_na)
