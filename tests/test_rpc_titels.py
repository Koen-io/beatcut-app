"""De twintig titelstijlen: catalogus, EDL, render en wat je echt ziet.

De proef die ertoe doet staat onderaan: elke stijl wordt los gerenderd op een
korte testclip en daarna nagekeken door `review.py`. Groen betekent hier
precies één ding — de titel is als zichtbaar beeld in de video terechtgekomen.
Een stijl die alleen in een catalogus bestaat is geen stijl.

Drie stijlen gaan daarnaast door 9:16, want daar valt tekst buiten beeld als
de maat niet meeschaalt met de korte zijde.
"""

import json
import subprocess
from pathlib import Path

import pytest
from cve import paths, titelstijl
from cve.edl import EDL, Canvas, Overgang, OverlayBlok, VideoBlok
from cve.render import RenderOpties
from cve.render import render as _render
from cve.review import _alfa_kader, review

from test_rpc_montage import _maak_clip
from test_rpc_project import _vraag

ALLE = [x["id"] for x in titelstijl.specs()]
# Deze drie zijn het strengst op een staand formaat: Slam is displaytype op
# volle breedte, Coordinaten heeft een ondertekst erbij, Gestapeld zet de
# plaatsnaam over meerdere regels.
STAAND = ["slam", "coords", "gestapeld"]

CLIP_S = 4
TITELTEKST = {
    "titel": "Garmisch-Partenkirchen",
    "eyebrow": "14 augustus",
    "onder": "700 m",
    "datum": "14 08 '26",
    "coords": "47,49° N · 11,10° O",
    "nummer": 1,
}


def test_catalogus_heeft_twintig_stijlen_met_een_eigen_id():
    assert len(ALLE) == 20
    assert len(set(ALLE)) == 20
    for s in titelstijl.specs():
        assert s["naam"] and s["animatie"], s["id"]
        assert s["font"] and s["grootte"] > 0, s["id"]


def test_onbekende_stijl_wordt_geweigerd():
    with pytest.raises(ValueError, match="bestaat niet"):
        titelstijl.eis("bestaat-niet")


def test_elke_stijl_verwijst_naar_een_lettertype_dat_meegeleverd_is():
    """Een render mag nooit het internet nodig hebben (CLAUDE.md regel 5)."""
    css = (paths.BRANDS / "fonts" / "titelfonts.css").read_text(encoding="utf-8")
    for s in titelstijl.specs():
        familie = s["font"].split(",")[0].strip().strip("'\"")
        assert f"font-family: '{familie}'" in css, f"{s['id']}: {familie} ontbreekt"
    assert "https://" not in css, "titelfonts.css verwijst naar het internet"


def test_coordinaten_worden_leesbaar_geschreven():
    assert titelstijl._coords(47.4917, 11.0953) == "47,49° N · 11,10° O"
    assert titelstijl._coords(-33.9, -18.4) == "33,90° Z · 18,40° W"
    assert titelstijl._coords(None, None) == ""


def test_datumstempel_leest_als_een_camcorder():
    assert titelstijl._stempel("2026-08-14T10:11:12+0200") == "14 08 '26"
    assert titelstijl._stempel("") == ""


# --------------------------------------------------------------------------
# Renderen
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def titelproject(tmp_path_factory):
    """Eén project met één clip en een proxy; de EDL schrijft elke test zelf."""
    if not paths.heeft_ffmpeg():
        pytest.skip("ffmpeg/ffprobe niet gevonden")
    if paths.hyperframes() is None:
        pytest.skip("hyperframes niet gevonden")
    basis = tmp_path_factory.mktemp("titels")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "PROJECTEN", basis / "projecten")
        _vraag("project.maak", naam="titels")
        camera = basis / "camera"
        camera.mkdir()
        bron = camera / "clip-1.mp4"
        _maak_clip(bron, "null")
        _vraag("project.voegtoe", project="titels", paden=[str(bron)])

        pdir = paths.project_dir("titels")
        proxy = pdir / "proxies" / "C01.mp4"
        subprocess.run(
            [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(bron), "-vf", "scale=-2:360", "-c:v", "mpeg4", "-q:v", "3",
             "-an", str(proxy)],
            check=True, capture_output=True, timeout=300,
        )
        yield "titels", pdir


def _schrijf_edl(pdir: Path, stijl_id: str, breedte: int, hoogte: int) -> None:
    """Eén shot met één titel erover — verder niets dat in de weg kan zitten."""
    fps = 30
    frames = CLIP_S * fps - fps  # een seconde marge op het bronmateriaal
    edl = EDL(project="titels", canvas=Canvas(breedte=breedte, hoogte=hoogte, fps=fps))
    edl.video = [
        VideoBlok(
            id="B01", clip="C01", bestand="clip-1.mp4",
            bron_start=0.0, duur=frames / fps, tijdlijn_start=0.0,
            frames=frames, vulmodus="vul", zoom="geen",
            overgang_in=Overgang(soort="snede", duur=0.0),
        )
    ]
    edl.overlay = [
        OverlayBlok(
            id="o-titel1", soort="titel20", tijdlijn_start=0.3, duur=2.4,
            inhoud={**TITELTEKST, "titelstijl": stijl_id,
                    "spec": json.dumps(titelstijl.eis(stijl_id), ensure_ascii=False)},
        )
    ]
    # Een vorige render van dezelfde testmap zou anders hergebruikt worden.
    for oud in (pdir / "composities").glob("*.mov"):
        oud.unlink()
    edl.schrijf(pdir / "edl.json")


def _titels_groen(rapport) -> str:
    """De regel die zegt dat de titels echt in beeld staan, of de fout."""
    d = rapport.naar_dict()
    for b in d["bevindingen"]:
        if b["code"] == "overlay":
            return b["boodschap"]
        if b["code"].startswith("overlay_"):
            pytest.fail(f"{b['code']}: {b['boodschap']}")
    pytest.fail("geen enkele overlay-bevinding in het rapport")


@pytest.mark.parametrize("stijl_id", ALLE)
def test_titelstijl_komt_zichtbaar_in_de_video(titelproject, stijl_id, monkeypatch):
    project, pdir = titelproject
    monkeypatch.setattr(paths, "PROJECTEN", pdir.parent)
    _schrijf_edl(pdir, stijl_id, 640, 360)
    uit = _render(project, opties=RenderOpties(modus="preview"), log=lambda *_: None)
    assert uit.exists() and uit.stat().st_size > 0
    boodschap = _titels_groen(review(project, bestand=uit, log=lambda *_: None))
    assert "zichtbaar in beeld" in boodschap


@pytest.mark.parametrize("stijl_id", STAAND)
def test_titelstijl_blijft_in_beeld_op_negen_bij_zestien(titelproject, stijl_id, monkeypatch):
    """Geen letter buiten het kader, ook niet op een staand formaat.

    `_alfa_kader` geeft de omhullende rechthoek van het middelste frame — daar
    staat de animatie stil. Raakt die de rand, dan is er tekst afgesneden.
    """
    project, pdir = titelproject
    monkeypatch.setattr(paths, "PROJECTEN", pdir.parent)
    B, H = 360, 640
    _schrijf_edl(pdir, stijl_id, B, H)
    uit = _render(project, opties=RenderOpties(modus="preview"), log=lambda *_: None)
    _titels_groen(review(project, bestand=uit, log=lambda *_: None))

    kader = _alfa_kader(pdir / "composities" / "o-titel1.mov")
    assert kader is not None, f"{stijl_id}: geen zichtbare pixels"
    x0, y0, x1, y1 = kader
    # De slagschaduw loopt een paar pixels door; één procent speling.
    speling = max(2, round(B * 0.01))
    assert x0 >= 0 and y0 >= 0, f"{stijl_id}: kader begint buiten beeld {kader}"
    assert x1 <= B - 1 - speling, f"{stijl_id}: loopt rechts tot {x1} van {B}"
    assert y1 <= H - 1 - speling, f"{stijl_id}: loopt onder tot {y1} van {H}"
