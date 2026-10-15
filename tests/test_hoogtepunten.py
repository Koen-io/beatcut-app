"""Hoogtepunten en verhaalboog (13-10-2026).

De regisseur koos tot nu toe op kwaliteit; dit legt vast dat een moment
(geluidspiek, actiepiek) en nieuw beeld meetellen, en dat opening en slot
daar het zwaarst op letten.
"""

import numpy as np
import pytest
from cve.analyze import hoogtepunten as hp
from cve.analyze import inhoud
from cve.analyze import segmenten as seg_mod
from cve.director import preset as preset_mod
from cve import stijl as stijl_mod, paths


# -- metingen ----------------------------------------------------------------


def test_audiopiek_is_relatief_aan_de_eigen_achtergrond():
    stil = [-30.0] * 10
    stil[4] = -20.0  # 10 dB boven de rest: volle piek
    stil[7] = -25.0  # 5 dB: halve piek
    uit = hp.audiopiek(stil)
    assert uit[4] == 1.0
    assert uit[7] == pytest.approx(0.5, abs=0.01)
    assert uit[0] == 0.0
    # Een luide clip met dezelfde vorm krijgt dezelfde pieken.
    assert hp.audiopiek([x + 20 for x in stil]) == uit


def test_audiopiek_negeert_ruis_onder_de_stiltegrens():
    assert hp.audiopiek([-70.0, -60.0, -70.0]) == [0.0, 0.0, 0.0]
    assert hp.audiopiek([]) == []


def test_actiepiek_vindt_de_sprong_en_niet_het_gewone_bewegen():
    rustig = [0.3] * 20
    assert hp.actiepiek(rustig) == [0.0] * 20  # geen spreiding: geen piek
    met_sprong = list(rustig)
    met_sprong[10] = 0.9
    uit = hp.actiepiek(met_sprong)
    assert uit[10] == 1.0
    assert max(uit[:10] + uit[11:]) == 0.0


def test_nieuwheid_straft_de_derde_opname_van_hetzelfde():
    zelfde = 0b1010101010101010101010101010101010101010101010101010101010101010
    anders = zelfde ^ ((1 << 40) - 1)  # 40 van de 64 bits anders
    clips = [
        {"id": "C01", "reeks": {"hashes": [zelfde] * 5}},
        {"id": "C02", "reeks": {"hashes": [zelfde] * 5}},
        {"id": "C03", "reeks": {"hashes": [anders] * 5}},
        {"id": "C04", "reeks": {}},
    ]
    n = hp.nieuwheid(clips)
    assert n["C01"] == 0.0 and n["C02"] == 0.0
    assert n["C03"] == pytest.approx(40 / 64, abs=0.01)
    assert n["C04"] == 0.5
    assert hp.nieuwheid([clips[0]]) == {"C01": 1.0}


def test_nieuwheid_telt_hash_nul_als_echt_beeld():
    """Codex 14-10: dhash 0 (egaal beeld) werd weggefilterd en gaf bonus."""
    clips = [
        {"id": "C01", "reeks": {"hashes": [0] * 5}},
        {"id": "C02", "reeks": {"hashes": [0] * 5}},
    ]
    n = hp.nieuwheid(clips)
    assert n == {"C01": 0.0, "C02": 0.0}


def test_luidheid_leest_een_wav_op_de_meetmomenten(tmp_path):
    import soundfile as sf

    sr = 16000
    t = np.arange(sr * 3) / sr
    toon = np.sin(2 * np.pi * 440 * t) * 0.01  # zacht
    toon[sr : sr + sr // 2] *= 30.0  # tussen 1,0 en 1,5 s: hard
    sf.write(tmp_path / "a.wav", toon.astype("float32"), sr)
    db = hp.luidheid(tmp_path / "a.wav", [0.5, 1.25, 2.5])
    assert len(db) == 3
    assert db[1] > db[0] + 20 and db[1] > db[2] + 20
    assert hp.audiopiek(db) == [0.0, 1.0, 0.0]


def test_verrijk_zet_de_reeksen_erbij_ook_zonder_wav(tmp_path):
    clip = {
        "id": "C01",
        "proxy": "C01.mp4",
        "audio": {"heeft_audio": True},
        "reeks": {"tijden": [0.0, 0.5, 1.0, 1.5], "beweging": [0.1, 0.1, 0.8, 0.1], "hashes": [1, 1, 1, 1]},
    }
    hp.verrijk([clip], tmp_path)
    r = clip["reeks"]
    assert r["luidheid"] == [] and r["audiopiek"] == [0.0] * 4
    assert r["actiepiek"][2] > 0.8 and len(r["actiepiek"]) == 4
    assert clip["nieuwheid"] == 1.0


# -- in de segmentscore ------------------------------------------------------


def _clip(audiopiek, actiepiek, nieuwheid=0.0):
    n = len(audiopiek)
    return {
        "id": "C01",
        "duur": n * 0.5,
        "nieuwheid": nieuwheid,
        "reeks": {
            "tijden": [i * 0.5 for i in range(n)],
            "beweging": [0.5] * n,
            "scherpte": [0.8] * n,
            "belichting": [0.8] * n,
            "shake": [0.1] * n,
            "vlakheid": [0.2] * n,
            "audiopiek": audiopiek,
            "actiepiek": actiepiek,
        },
    }


def test_het_moment_wint_van_het_even_nette_stuk_zonder_moment():
    g = seg_mod.Gewichten()
    assert g.audiopiek > 0 and g.actiepiek > 0 and g.nieuwheid > 0
    n = 40
    piek = [0.0] * n
    piek[30] = piek[31] = piek[32] = 1.0
    stil = _clip([0.0] * n, [0.0] * n)
    met = _clip(piek, [0.0] * n)
    s_stil, o_stil = seg_mod.scoor_tijdlijn(stil, g)
    s_met, o_met = seg_mod.scoor_tijdlijn(met, g)
    assert "audiopiek" in o_met and "nieuwheid" in o_met
    assert s_met[31] > s_stil[31]
    assert s_met[5] == pytest.approx(s_stil[5])
    # Een oude analyse zonder de reeksen: zelfde score als voorheen.
    oud = _clip([0.0] * n, [0.0] * n)
    del oud["reeks"]["audiopiek"], oud["reeks"]["actiepiek"], oud["nieuwheid"]
    s_oud, _ = seg_mod.scoor_tijdlijn(oud, g)
    assert list(s_oud) == pytest.approx(list(s_stil))


def test_stijlbestanden_zonder_de_nieuwe_gewichten_krijgen_de_standaard():
    for naam in ("actie", "reis", "vlog", "landschap", "luchtvaart"):
        st = stijl_mod.laad(naam, paths.STYLES, met_geheugen=False)
        assert st.gewichten.audiopiek == seg_mod.Gewichten().audiopiek, naam
        assert "nieuwheid" in st.gewichten.signalen()


# -- de verhaalboog in de regisseur -----------------------------------------


def _segment(clip, start, score, **ond):
    basis = {"beweging": 0.5, "scherpte": 0.7, "audiopiek": 0.0, "actiepiek": 0.0, "nieuwheid": 0.0}
    basis.update(ond)
    return {"clip": clip, "scene": 0, "start": start, "eind": start + 2.0, "duur": 2.0,
            "score": score, "onderdelen": basis}


def _kies(segmenten, **extra):
    r = preset_mod.PresetRegisseur()
    st = stijl_mod.laad("reis", paths.STYLES, met_geheugen=False)
    clips = {"C01": {"id": "C01", "reeks": {}}, "C02": {"id": "C02", "reeks": {}}}
    kw = dict(bron_nodig=2.0, niveau="midden", gebruikt=set(), recente_clips=[],
              recente_hashes=[], recente_scenes=[], clip_op_id=clips, eerste=False, st=st)
    kw.update(extra)
    keuze = r._kies(segmenten, **kw)
    assert keuze is not None
    return keuze[0]["clip"]


def test_opening_en_slot_kiezen_het_moment_boven_het_net_iets_nettere_shot():
    net = _segment("C01", 0.0, 0.62, scherpte=0.9)
    moment = _segment("C02", 0.0, 0.55, scherpte=0.7, audiopiek=0.9, nieuwheid=0.6)
    assert _kies([net, moment]) == "C01"  # gewoon vak: de hoogste score wint
    assert _kies([net, moment], eerste=True) == "C02"
    assert _kies([net, moment], laatste=True) == "C02"
    assert _kies([net, moment], niveau="hoog") == "C02"


def test_het_laatste_vak_van_het_raster_krijgt_het_slot(monkeypatch):
    """`laatste` komt alleen op het laatste vak, ook met een doelduur."""
    gezien = []
    r = preset_mod.PresetRegisseur()
    echte = r._kies

    def spion(*a, **k):
        gezien.append(bool(k.get("laatste")))
        return echte(*a, **k)

    monkeypatch.setattr(r, "_kies", spion)
    # Twee vakken van 2 s, één segment per clip, geen muziek: via het
    # min_shot-raster van de stijl.
    analyse = {
        "project": "p",
        "clips": [{"id": "C01", "bestand": "a.mp4", "duur": 10.0, "reeks": {}},
                  {"id": "C02", "bestand": "b.mp4", "duur": 10.0, "reeks": {}}],
        "segmenten": [_segment("C01", 0.0, 0.6), _segment("C02", 0.0, 0.6),
                      _segment("C01", 5.0, 0.5), _segment("C02", 5.0, 0.5)],
        "gewichten": {},
    }
    from cve.director.basis import Brief

    r.stel_voor(analyse, Brief(stijl="reis", vorm="16:9", doelduur=4.0))
    assert gezien, "geen keuze gemaakt"
    assert gezien[-1] is True
    assert gezien[0] is False
    # Alleen het laatste vak draagt het slot, hoeveel soepelheidsniveaus het
    # ook nodig had.
    assert all(gezien[i] is False for i in range(len(gezien)) if i < gezien.index(True))


def test_inhoud_zonder_model_is_onbekend_geen_fout():
    m = inhoud.kies_model()
    assert m.beschikbaar() is False
    assert m.bekijk("x.jpg").embedding is None
    assert inhoud.gelijkenis(None, [1.0]) is None
    assert inhoud.gelijkenis([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert inhoud.gelijkenis([1.0, 0.0], [-1.0, 0.0]) == 0.0
