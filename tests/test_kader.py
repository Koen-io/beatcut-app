"""Herkaderen: één tabel getallen, twee implementaties.

De export snijdt met `ffmpeg crop`, de voorvertoning met een uv-verschuiving in
de shader. Twee keer dezelfde wiskunde, dus twee kansen om uit elkaar te lopen.
`tests/kader-gevallen.json` is de afspraak: deze test legt de Python-kant
ertegen aan, `app/tests/kader.test.ts` de TypeScript-kant.

En er is één echte meting bij: ffmpeg krijgt de crop-uitdrukking die de
renderer bouwt, en moet frame voor frame hetzelfde opleveren als een crop op de
plek die `kader.py` uitrekent. Zonder die meting toetsen we alleen of twee
Python-functies met zichzelf overeenstemmen.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cve import kader, paths, render
from cve.edl import EDL, Canvas, EDLFout, VideoBlok

GEVALLEN = json.loads(
    (Path(__file__).with_name("kader-gevallen.json")).read_text(encoding="utf-8")
)["gevallen"]


def _blok(**kw) -> VideoBlok:
    return VideoBlok(id="v001", clip="C01", bestand="a.mp4", bron_start=0.0,
                     duur=2.0, tijdlijn_start=0.0, **kw)


def _vul(geval: dict) -> dict:
    """Wat de speler voor dit geval uitrekent, in Python. Zie `kaderVul()`."""
    b0, h0 = kader.venster(geval["bronverhouding"], geval["canvasverhouding"])
    x0 = kader.schuif(b0, geval["kaderX"])
    y0 = kader.schuif(h0, geval["kaderY"])
    z = max(1e-4, geval["zoom"])
    b, h = b0 / z, h0 / z
    ruimte_x, ruimte_y = (b0 - b) / 2, (h0 - h) / 2
    return {
        "schaalX": b,
        "schaalY": h,
        "schuifX": x0 + ruimte_x + geval["panX"] * ruimte_x,
        "schuifY": y0 + ruimte_y + geval["panY"] * ruimte_y,
    }


@pytest.mark.parametrize("geval", GEVALLEN, ids=[g["naam"] for g in GEVALLEN])
def test_de_tabel_klopt_met_de_wiskunde_van_de_engine(geval):
    gemeten = _vul(geval)
    for veld, verwacht in geval["verwacht"].items():
        assert gemeten[veld] == pytest.approx(verwacht, abs=1e-6), veld


def test_het_venster_blijft_binnen_de_bron():
    """Een onderwerp tegen de rand trekt het venster niet buiten het beeld."""
    b, _ = kader.venster(16 / 9, 9 / 16)
    assert kader.schuif(b, 0.0) == 0.0
    assert kader.schuif(b, 1.0) == pytest.approx(1 - b)
    assert kader.schuif(1.0, 0.0) == 0.0  # geen ruimte = geen schuif


def test_de_as_met_ruimte():
    assert kader.as_met_ruimte(16 / 9, 9 / 16) == "x"
    assert kader.as_met_ruimte(9 / 16, 16 / 9) == "y"
    assert kader.as_met_ruimte(16 / 9, 16 / 9) is None


def test_een_gedraaide_clip_telt_als_staand():
    """iPhone-opnames staan als 3840x2160 in het bestand, met een rotatievlag."""
    assert kader.bronverhouding(
        {"breedte": 3840, "hoogte": 2160, "verticaal": True}
    ) == pytest.approx(2160 / 3840)
    assert kader.bronverhouding(
        {"breedte": 3840, "hoogte": 2160, "verticaal": False}
    ) == pytest.approx(3840 / 2160)


def test_keyframes_lopen_lineair():
    k = {"punten": [{"t": 0.0, "x": 0.2, "y": 0.5}, {"t": 1.0, "x": 0.8, "y": 0.5}]}
    assert kader.punt_op(k, 0.0)[0] == pytest.approx(0.2)
    assert kader.punt_op(k, 0.5)[0] == pytest.approx(0.5)
    assert kader.punt_op(k, 1.0)[0] == pytest.approx(0.8)
    # Buiten het bereik vasthouden, niet doorschieten.
    assert kader.punt_op(k, 2.0)[0] == pytest.approx(0.8)
    assert kader.punt_op({}) == (0.5, 0.5)


def test_een_oude_edl_zonder_kader_rendert_precies_zoals_eerst():
    """Regel: een bestaande edl.json mag niet anders gaan renderen."""
    f = render._pasfilter(_blok(vulmodus="vul"), Canvas(1080, 1920, 30))
    assert f.endswith("crop=1080:1920")


def test_de_validatie_wijst_een_onmogelijk_kader_af():
    e = EDL(project="p")
    b = _blok()
    e.video.append(b)
    for slecht in ({"x": 1.4}, {"x": 0.3, "punten": [{"t": 0.0, "x": 0.5}]},
                   {"punten": []}, {"zweef": 1}, {"punten": [{"t": 0.5}, {"t": 0.2}]}):
        b.kader = slecht
        with pytest.raises(EDLFout):
            e.valideer()
    b.kader = {"x": 0.3, "y": 0.5}
    e.valideer()


# --------------------------------------------------------------------------
# De meting: wat ffmpeg er echt van maakt
# --------------------------------------------------------------------------


def _framemd5(vf: str, bron: str) -> list[str]:
    r = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-f", "lavfi", "-i", bron,
         "-vf", vf, "-f", "framemd5", "-"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.splitlines() if l and not l.startswith("#")]


@pytest.mark.skipif(paths.ffmpeg() is None, reason="geen ffmpeg")
@pytest.mark.parametrize("geval", [g for g in GEVALLEN if g["zoom"] == 1.0],
                         ids=[g["naam"] for g in GEVALLEN if g["zoom"] == 1.0])
def test_ffmpeg_snijdt_waar_de_speler_kijkt(geval):
    """De crop van de renderer landt op de fractie die de speler gebruikt.

    Beide kanten laten we door ffmpeg zelf uitrekenen: de uitdrukking die
    `_pasfilter` bouwt, en een crop op `iw * schuifX`. Dat is precies wat de
    shader doet met `schuifX`. Zelfde frames, zelfde md5.

    Ken Burns zit hier niet in - dat is stap 2 en loopt in de export via
    `zoompan` op een opgeschaald beeld; die stap heeft zijn eigen
    gouden-frames-meting.
    """
    cb, ch = geval["canvas"]
    canvas = Canvas(breedte=cb, hoogte=ch, fps=30)
    blok = _blok(vulmodus="vul", kader={"x": geval["kaderX"], "y": geval["kaderY"]})

    bronverhouding = geval["bronverhouding"]
    bb, bh = (1920, 1080) if bronverhouding > 1 else (1080, 1920)
    bron = f"testsrc2=size={bb}x{bh}:rate=30:duration=0.2"

    schaal = f"scale={cb}:{ch}:force_original_aspect_ratio=increase:flags=bicubic"
    verwacht = geval["verwacht"]
    referentie = (
        f"{schaal},crop={cb}:{ch}"
        f":x=iw*{verwacht['schuifX']:.9f}:y=ih*{verwacht['schuifY']:.9f}"
    )
    assert _framemd5(render._pasfilter(blok, canvas), bron) == _framemd5(referentie, bron)


@pytest.mark.skipif(paths.ffmpeg() is None, reason="geen ffmpeg")
def test_ffmpeg_slikt_een_kader_op_keyframes():
    """Keyframes worden een uitdrukking in `t`; ffmpeg moet die aankunnen.

    En halverwege moet hij op hetzelfde punt staan als `kader.punt_op()`: dat
    is wat de speler op dat moment laat zien.
    """
    k = {"punten": [{"t": 0.0, "x": 0.1, "y": 0.5}, {"t": 1.0, "x": 0.9, "y": 0.5}]}
    blok = _blok(vulmodus="vul", kader=k)
    blok.duur = 1.0
    canvas = Canvas(1080, 1920, 30)
    bron = "testsrc2=size=1920x1080:rate=30:duration=1"

    # Eén frame op de helft, uit de bewegende crop en uit een vaste crop op het
    # punt dat de speler daar berekent.
    midden_x = kader.punt_op(k, 0.5)[0]
    b, _ = kader.venster(1920 / 1080, 1080 / 1920)
    vast = (
        f"scale=1080:1920:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop=1080:1920:x=iw*{kader.schuif(b, midden_x):.9f}:y=0"
    )
    knip = "trim=start=0.5:end=0.534,setpts=PTS-STARTPTS"
    assert _framemd5(f"{render._pasfilter(blok, canvas)},{knip}", bron) == _framemd5(
        f"{vast},{knip}", bron
    )
