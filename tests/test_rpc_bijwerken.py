"""Stap 4 — Bijwerken: de montage opvragen, één shot bijstellen, opnieuw regisseren.

Drie beweringen die ertoe doen:

1. de shots liggen op het tel-raster (binnen één frame — de EDL is framevast
   gemaakt, de tellen van librosa zijn dat niet);
2. een shot bijstellen verschuift *niets* op de tijdlijn;
3. "nooit gebruiken" haalt een clip uit de montage, "moet erin" zet hem erin.

Het project komt uit `test_rpc_montage`: dezelfde drie gegenereerde clips en
dezelfde kicktrack van 120 BPM.
"""

import json
from pathlib import Path

import pytest
from cve import bijwerken, paths

from test_rpc_montage import (  # noqa: F401 — fixtures komen hier vandaan
    _wacht_op_einde,
    _zet_muziek,
    montageproject,
    opgevangen,
)
from test_rpc_project import _vraag, nodig_ffmpeg

DUURTJE = 8.0  # doelduur van de montages in deze test, in seconden
# De montagestijl van de fixture: één shot per maat, op 120 BPM dus twee
# seconden. Kort genoeg dat `test_shot_zet_laat_de_tijdlijn_staan` een shot op
# 1,5x kan zetten zonder dat de bronclip te kort wordt.
MONTAGE = "cine"
# En de rustigste stijl, voor de ene test die een montage nodig heeft waarin
# niet alle clips passen: zeven seconden per shot, dus twee shots in `DUURTJE`.
MONTAGE_RUSTIG = "ambient"


@pytest.fixture
def gemonteerd(montageproject):  # noqa: F811
    """Een project met muziek en een verse montage, zonder render."""
    project, basis = montageproject
    _zet_muziek(project, basis)
    bijwerken.zet_voorkeur(project, "clip-1.mp4", None)
    bijwerken.zet_voorkeur(project, "clip-2.mp4", None)
    bijwerken.zet_voorkeur(project, "clip-3.mp4", None)
    _vraag(
        "project.regisseer", project=project, stijl="reis", montage=MONTAGE,
        vorm="16:9", duur=DUURTJE,
    )
    return project, basis


@nodig_ffmpeg
def test_montage_geeft_shots_op_het_tel_raster(gemonteerd):
    project, _ = gemonteerd
    m = _vraag("project.montage", project=project)

    assert m["shots"], m
    assert m["tellen"] == sorted(m["tellen"])
    assert m["tellen"][0] == pytest.approx(0.0, abs=1e-3)
    assert m["maten"] and m["maten"][0]["nummer"] == 1
    assert 0 < len(m["golfvorm"]) <= bijwerken.GOLF_PUNTEN

    frame = 1.0 / m["fps"]
    for s in m["shots"]:
        assert s["tel"] is not None, s
        # Precies op de tel: wat eraf is, is de afronding op hele frames en
        # niets anders. Zie `EDL.op_framerooster`.
        assert abs(s["tel_afwijking"]) <= frame + 1e-3, s
        assert s["start"] == pytest.approx(m["tellen"][s["tel"]], abs=frame + 1e-3)
        assert s["tellen"] >= 1
        assert s["thumbnail"] and Path(s["thumbnail"]).exists()
        assert m["clips"][s["clip"]]["strip"], "filmstrip ontbreekt"

    # De sporen uit het ontwerp hangen aan dezelfde tijdlijn.
    assert m["duur"] == pytest.approx(
        max(s["start"] + s["duur"] for s in m["shots"]), abs=1e-3
    )


@nodig_ffmpeg
def test_shot_zet_laat_de_tijdlijn_staan(gemonteerd):
    project, _ = gemonteerd
    voor = _vraag("project.montage", project=project)
    doel = voor["shots"][len(voor["shots"]) // 2]
    tijden = [(s["id"], s["start"], s["duur"], s["frames"]) for s in voor["shots"]]

    na = _vraag(
        "project.shot.zet",
        project=project,
        shot=doel["id"],
        snelheid=1.5,
        bron_in=doel["bron_in"] + 1.0,
    )

    assert [(s["id"], s["start"], s["duur"], s["frames"]) for s in na["shots"]] == tijden
    nieuw = next(s for s in na["shots"] if s["id"] == doel["id"])
    assert nieuw["snelheid"] == 1.5
    assert nieuw["bron_in"] > doel["bron_in"]
    assert nieuw["bron_duur"] == pytest.approx(nieuw["duur"] * 1.5, abs=1e-3)
    # Het venster blijft binnen de clip.
    clip = na["clips"][nieuw["clip"]]
    assert nieuw["bron_in"] + nieuw["bron_duur"] <= clip["duur"] + 1e-3

    # En op schijf staat het ook zo — `edl.json` is de enige waarheid.
    edl = json.loads((paths.PROJECTEN / project / "edl.json").read_text())
    blok = next(b for b in edl["video"] if b["id"] == doel["id"])
    assert blok["snelheid"] == 1.5
    assert blok["tijdlijn_start"] == doel["start"]
    assert blok["frames"] == doel["frames"]


@nodig_ffmpeg
def test_moet_zet_een_clip_erin_en_nooit_haalt_hem_weg(gemonteerd):
    """De scherpste proef: een clip die de regisseur zelf niet koos.

    Met een doelduur van 8 s en montagestijl `ambient` passen er twee shots in,
    dus één van de drie clips blijft liggen. Juist die zet de test op "moet erin".
    """
    project, _ = gemonteerd
    begin = _vraag(
        "project.regisseer", project=project, stijl="reis", montage=MONTAGE_RUSTIG,
        vorm="16:9", duur=DUURTJE,
    )["montage"]
    gebruikt = {s["bestand"] for s in begin["shots"]}
    alle = {c["naam"] for c in _vraag("project.clips", project=project)}
    afwezig = sorted(alle - gebruikt)
    assert afwezig, "alle clips zitten er al in; dan bewijst deze test niets"
    clip = afwezig[0]

    uit = _vraag("project.clip.voorkeur", project=project, clip=clip, soort="moet")
    assert uit["moet"] == [clip]
    na = _vraag(
        "project.regisseer", project=project, stijl="reis", montage=MONTAGE_RUSTIG,
        vorm="16:9", duur=DUURTJE,
    )
    shots = na["montage"]["shots"]
    assert clip in [s["bestand"] for s in shots], na["waarschuwingen"]
    assert next(s for s in shots if s["bestand"] == clip)["moet"]

    uit = _vraag("project.clip.voorkeur", project=project, clip=clip, soort="nooit")
    assert uit["moet"] == [] and uit["nooit"] == [clip]
    weg = _vraag(
        "project.regisseer", project=project, stijl="reis", montage=MONTAGE_RUSTIG,
        vorm="16:9", duur=DUURTJE,
    )
    assert weg["montage"]["shots"], "zonder die clip valt de montage stil"
    assert clip not in [s["bestand"] for s in weg["montage"]["shots"]]

    # De keuzes zijn ook geleerd: `keuzes.json` houdt bij wat de gebruiker zei.
    keuzes = json.loads((paths.PROJECTEN / project / "keuzes.json").read_text())["keuzes"]
    assert {k["soort"] for k in keuzes} == {"verwijderd", "vastgezet"}


@nodig_ffmpeg
def test_maak_video_zonder_regie_houdt_de_bijgewerkte_montage(gemonteerd, opgevangen):  # noqa: F811
    """De knop "Maak video" in stap 4 mag het eigen werk niet weggooien.

    Zonder `regie: false` bedenkt `maak_video` de montage opnieuw, en dan is
    elke bijstelling uit deze stap weg bij de eerste klik.
    """
    project, _ = gemonteerd
    m = _vraag("project.shot.zet", project=project, shot="v001", snelheid=2.0)
    voor = [(s["id"], s["start"], s["duur"], s["snelheid"]) for s in m["shots"]]
    opgevangen.clear()

    assert _vraag(
        "project.maakvideo", project=project, stijl="reis", montage=MONTAGE,
        vorm="16:9", duur=DUURTJE, kwaliteit="preview", regie=False,
    ) == {"gestart": True}
    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde
    assert "Jouw montage" in einde["data"]["uitleg"]
    assert Path(einde["data"]["video"]).exists()

    na = _vraag("project.montage", project=project)
    assert [(s["id"], s["start"], s["duur"], s["snelheid"]) for s in na["shots"]] == voor


@nodig_ffmpeg
def test_export_op_volle_kwaliteit_regisseert_niet_opnieuw(gemonteerd, opgevangen):  # noqa: F811
    """"Exporteer op volle kwaliteit" stuurt géén `regie` mee — en mag niets weggooien.

    Dit is de bevinding uit de tegenlezing: de interface hield zelf bij of er
    met de hand gemonteerd was, en vergat dat bij te werken. De regel staat nu
    in de engine, dus de interface kán het niet meer fout doen.
    """
    project, _ = gemonteerd
    m = _vraag("project.shot.zet", project=project, shot="v001", snelheid=2.0)
    voor = [(s["id"], s["start"], s["duur"], s["snelheid"]) for s in m["shots"]]
    opgevangen.clear()

    assert _vraag(
        "project.maakvideo", project=project, stijl="reis", montage=MONTAGE,
        vorm="16:9", duur=DUURTJE, kwaliteit="preview",
    ) == {"gestart": True}
    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde
    assert "Jouw montage" in einde["data"]["uitleg"]

    na = _vraag("project.montage", project=project)
    assert [(s["id"], s["start"], s["duur"], s["snelheid"]) for s in na["shots"]] == voor


@nodig_ffmpeg
def test_alleen_een_andere_keuze_in_stijl_start_een_nieuwe_regie(gemonteerd):  # noqa: F811
    from cve import montage as montage_mod

    project, _ = gemonteerd
    zelfde = dict(stijl="reis", montage=MONTAGE, vorm="16:9", duur=DUURTJE)
    assert not montage_mod.regie_nodig(project, **zelfde)
    assert montage_mod.regie_nodig(project, **{**zelfde, "stijl": "actie"})
    assert montage_mod.regie_nodig(project, **{**zelfde, "montage": "velocity"})
    assert montage_mod.regie_nodig(project, **{**zelfde, "vorm": "9:16"})
    assert montage_mod.regie_nodig(project, **{**zelfde, "duur": None})


def test_snelheid_wordt_begrensd_door_de_bronclip(tmp_path, monkeypatch):
    """Een shot van 4 s op 2x vraagt 8 s bron; de clip heeft er 5.

    Alleen `bron_in` begrenzen hielp niet — ffmpeg leverde 75 van de
    gevraagde 120 frames en alles erna schoof van de beat. De snelheid geeft
    dus mee, en de tijdlijn blijft exact staan.

    De montage zelf doet hier niet mee (die heeft proxies en een analyse
    nodig); de bewering gaat over wat er in `edl.json` terechtkomt.
    """
    from cve.edl import EDL, Canvas, VideoBlok

    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    monkeypatch.setattr(bijwerken, "montage", lambda project: {})
    pdir = tmp_path / "krap"
    pdir.mkdir()
    (pdir / "ingest.json").write_text(
        json.dumps({"clips": [{"id": "C01", "bestand": "a.mp4", "proxy": "a.mp4", "duur": 5.0}]}),
        encoding="utf-8",
    )
    EDL(
        project="krap",
        canvas=Canvas(),
        video=[
            VideoBlok(id="S1", clip="C01", bestand="a.mp4", bron_start=0.5,
                      duur=4.0, tijdlijn_start=2.0)
        ],
    ).schrijf(pdir / "edl.json")

    bijwerken.zet_shot("krap", "S1", snelheid=2.0)

    blok = EDL.lees(pdir / "edl.json").video[0]
    assert blok.snelheid == 1.25, blok.snelheid
    assert blok.bron_start + blok.duur * blok.snelheid <= 5.0 + 1e-9
    assert blok.tijdlijn_start == 2.0 and blok.duur == 4.0


@nodig_ffmpeg
def test_montage_stuurt_de_rampstukken_mee_voor_de_voorvertoning(gemonteerd):
    """De speler moet een speed-ramp net zo integreren als de renderer.

    `project.montage` stuurt daarom dezelfde (uitvoerduur, snelheid)-stukken
    mee als `VideoBlok.snelheid_stukken()`. Zonder die lijst speelt de
    voorvertoning een ramp-shot op constante snelheid: bij een shot van vier
    seconden met een ramp van 1x naar 2x eet de render zes seconden bron en de
    speler maar vier. Zie app/src/speler/demux.ts (`brontijdVan`).
    """
    project, _ = gemonteerd
    m = _vraag("project.montage", project=project)

    assert m["shots"], m
    for s in m["shots"]:
        stukken = s["snelheid_stukken"]
        assert stukken, s
        # De som van de uitvoerduren is de blokduur, de integraal van
        # snelheid x duur is precies het bronmateriaal dat het blok opmaakt.
        assert sum(d for d, _ in stukken) == pytest.approx(s["duur"], abs=1e-3)
        assert sum(d * v for d, v in stukken) == pytest.approx(s["bron_duur"], abs=1e-3)
        assert (len(stukken) > 1) == s["ramp"], s
        if not s["ramp"]:
            assert stukken == [[pytest.approx(s["duur"], abs=1e-3), s["snelheid"]]]

    # En een shot op 1,5x levert stukken die daarmee meebewegen.
    doel = m["shots"][0]
    na = _vraag("project.shot.zet", project=project, shot=doel["id"], snelheid=1.5)
    nieuw = next(s for s in na["shots"] if s["id"] == doel["id"])
    assert nieuw["snelheid_stukken"] == [[pytest.approx(nieuw["duur"], abs=1e-3), 1.5]]
