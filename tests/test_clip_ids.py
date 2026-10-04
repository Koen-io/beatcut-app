"""Een clip-id blijft van een bestand. Anders wijst een bestaande `edl.json`
na één extra clip naar andere beelden."""

import json

from cve.ingest import wijs_ids_toe


def test_clip_erbij_laat_bestaande_ids_ongemoeid(tmp_path):
    # Eerste keer inlezen: chronologisch, dus C01..C03.
    eerst = wijs_ids_toe(tmp_path, ["b.mov", "c.mov", "d.mov"])
    assert eerst == {"b.mov": "C01", "c.mov": "C02", "d.mov": "C03"}

    # Een clip die chronologisch vóóraan valt komt erbij.
    opnieuw = wijs_ids_toe(tmp_path, ["a.mov", "b.mov", "c.mov", "d.mov"])
    assert opnieuw["a.mov"] == "C04"
    for naam, cid in eerst.items():
        assert opnieuw[naam] == cid


def test_verwijderd_bestand_geeft_zijn_nummer_niet_weg(tmp_path):
    wijs_ids_toe(tmp_path, ["a.mov", "b.mov"])
    assert wijs_ids_toe(tmp_path, ["a.mov", "nieuw.mov"]) == {
        "a.mov": "C01",
        "nieuw.mov": "C03",
    }


def test_migratie_neemt_de_ids_uit_een_bestaande_ingest_over(tmp_path):
    """Een project van vóór `clips.json` heeft zijn id's in `ingest.json`.

    Werd dat niet gelezen, dan begon de nummering opnieuw: een clip die
    chronologisch vóór de bestaande valt pakt C01 af, terwijl de proxy van
    C01 nog bij de oude beelden hoort.
    """
    (tmp_path / "ingest.json").write_text(
        json.dumps(
            {
                "clips": [
                    {"id": "C01", "bestand": "b.mov", "proxy": "C01_b.mp4"},
                    {"id": "C02", "bestand": "c.mov", "proxy": "C02_c.mp4"},
                ]
            }
        ),
        encoding="utf-8",
    )

    ids = wijs_ids_toe(tmp_path, ["a.mov", "b.mov", "c.mov"])
    assert ids == {"a.mov": "C03", "b.mov": "C01", "c.mov": "C02"}

    # En de overname is eenmalig vastgelegd: `clips.json` kent ze nu ook.
    bekend = json.loads((tmp_path / "clips.json").read_text(encoding="utf-8"))["ids"]
    assert bekend["b.mov"] == "C01"
