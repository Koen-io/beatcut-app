"""Een moet-clip zonder lang genoeg stuk wordt binnen de clip opgerekt."""
from cve.director.preset import PresetRegisseur as R  # noqa: N814


def test_te_kort_stuk_wordt_venster_binnen_de_clip():
    seg = {"clip": "C1", "start": 1.0, "eind": 3.0, "duur": 2.0, "score": 0.5}
    breed = R._verbreed(seg, 4.0, {"C1": {"duur": 10.0}})
    assert breed["duur"] == 4.0 and breed["start"] == 0.0 and breed["eind"] == 4.0
    assert breed["score"] < seg["score"]


def test_clip_korter_dan_het_shot_blijft_weg():
    seg = {"clip": "C1", "start": 0.0, "eind": 2.0, "duur": 2.0, "score": 0.5}
    assert R._verbreed(seg, 4.0, {"C1": {"duur": 3.0}}) is None
