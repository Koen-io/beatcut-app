"""De EDL is volgens regel 3 de enige waarheid. Opslaan mag hem nooit kwijtraken,
en een oud bestand moet blijven laden."""

import json
from pathlib import Path

import pytest

from cve.edl import SCHEMA_VERSIE, EDL, EDLFout, VideoBlok

# Een echte montage van een eerdere render. `projecten/` staat niet in git en
# elke render schrijft dit bestand opnieuw — zodra hij op versie 2 staat, valt
# de test terug op de fixture hieronder. Anders zou een gewone render de test
# breken op iets wat niets met het schema te maken heeft.
BESTAAND = Path(__file__).resolve().parent.parent / "projecten" / "test" / "edl.json"


def _oude_edl() -> dict:
    if BESTAAND.exists():
        ruw = json.loads(BESTAAND.read_text(encoding="utf-8"))
        if ruw.get("versie") == 1:
            return ruw
    return OUD_FIXTURE

OUD_FIXTURE = {
    "versie": 1,
    "project": "fixture",
    "stijl": "reis",
    "merk": "prive",
    "canvas": {"breedte": 1920, "hoogte": 1080, "fps": 30},
    "grade": {"contrast": 1.08, "verzadiging": 1.12, "helderheid": 0.0, "warmte": 0.08},
    "video": [
        {
            "id": "v001",
            "clip": "C01",
            "bestand": "IMG_0001.MOV",
            "bron_start": 1.0,
            "duur": 2.0,
            "tijdlijn_start": 0.0,
            "frames": 60,
            "overgang_in": {"soort": "crossfade", "duur": 0.25},
        }
    ],
    "audio": [],
    "overlay": [],
}


def _edl(notitie: str = "") -> EDL:
    return EDL(
        project="proef",
        notities=notitie,
        video=[
            VideoBlok(
                id="v001",
                clip="C01",
                bestand="a.mov",
                bron_start=0.0,
                duur=2.0,
                tijdlijn_start=0.0,
            )
        ],
    )


def test_afgebroken_schrijfactie_laat_het_oude_bestand_heel(tmp_path, monkeypatch):
    pad = _edl("eerste").schrijf(tmp_path / "edl.json")
    goed = pad.read_text(encoding="utf-8")

    echt = Path.write_text

    def halverwege(self, data, **kw):
        echt(self, data[: len(data) // 2], **kw)  # stroom valt eruit
        raise OSError("stroom eruit")

    monkeypatch.setattr(Path, "write_text", halverwege)
    with pytest.raises(OSError):
        _edl("tweede").schrijf(pad)

    assert pad.read_text(encoding="utf-8") == goed
    assert EDL.lees(pad).notities == "eerste"


def test_vorige_versie_blijft_bewaard(tmp_path):
    pad = _edl("eerste").schrijf(tmp_path / "edl.json")
    _edl("tweede").schrijf(pad)
    assert EDL.lees(pad).notities == "tweede"
    assert EDL.lees(tmp_path / "edl.vorige.json").notities == "eerste"


def test_oude_edl_laadt_en_krijgt_de_nieuwe_velden(tmp_path):
    ruw = _oude_edl()
    assert ruw["versie"] == 1, "deze test gaat juist over het oude schema"

    edl = EDL.van_dict(ruw)
    assert edl.look.id == "geen"
    assert edl.afwerking.korrel == 0.0
    assert edl.effectseed == 0
    assert edl.video[0].snelheid_verloop == []

    pad = edl.schrijf(tmp_path / "edl.json")
    opnieuw = json.loads(pad.read_text(encoding="utf-8"))
    assert opnieuw["versie"] == SCHEMA_VERSIE
    assert EDL.lees(pad).naar_dict() == edl.naar_dict()


def test_speed_ramp_overleeft_opslaan_en_inlezen(tmp_path):
    e = _edl()
    e.video[0].snelheid_verloop = [
        {"t": 0.0, "snelheid": 1.0},
        {"t": 0.5, "snelheid": 0.3},
        {"t": 1.0, "snelheid": 2.5},
    ]
    pad = e.schrijf(tmp_path / "edl.json")
    assert EDL.lees(pad).video[0].snelheid_verloop == e.video[0].snelheid_verloop


def test_verkeerde_speed_ramp_en_onbekende_overgang_worden_geweigerd(tmp_path):
    e = _edl()
    e.video[0].snelheid_verloop = [{"t": 0.6, "snelheid": 1.0}, {"t": 0.2, "snelheid": 1.0}]
    with pytest.raises(EDLFout):
        e.schrijf(tmp_path / "edl.json")

    e = _edl()
    e.video[0].overgang_in.soort = "sterretjes"
    with pytest.raises(EDLFout):
        e.schrijf(tmp_path / "edl.json")
