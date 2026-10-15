"""Importeren en analyseren via het RPC-protocol, met echte videobestanden.

Twee clips van 2 s die ffmpeg zelf genereert (testsrc2 + sine). Klein genoeg
om in een paar seconden door ingest en analyse te gaan, echt genoeg om te
bewijzen dat de hele keten loopt: proxies, beeldanalyse, segmenten, beeldjes.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest
from cve import paths, rpc
from cve import projecten as projecten_mod


def _maak_clip(doel, *, seconden: int = 2) -> None:
    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={seconden}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconden}",
            # mpeg4: zit in elke ffmpeg-build, ook de LGPL-variant die mee gaat
            "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(doel),
        ],
        check=True, capture_output=True, timeout=120,
    )


@pytest.fixture
def losse_projectmap(tmp_path, monkeypatch):
    """Projecten in een tijdelijke map. `paths.PROJECTEN` is een constante die
    bij het importeren gezet wordt, dus hier omzetten in plaats van via de
    omgevingsvariabele - die komt te laat."""
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    return tmp_path


@pytest.fixture
def opgevangen(monkeypatch):
    """Alles wat de engine naar stdout zou schrijven, als lijst."""
    regels: list[dict] = []
    monkeypatch.setattr(rpc, "_schrijf", regels.append)
    return regels


def _vraag(methode: str, **params):
    antwoord = rpc.verwerk(json.dumps({"id": 1, "methode": methode, "params": params}))
    assert "fout" not in antwoord, antwoord
    return antwoord["resultaat"]


nodig_ffmpeg = pytest.mark.skipif(
    not paths.heeft_ffmpeg(), reason="ffmpeg/ffprobe niet gevonden"
)


def test_maak_en_voegtoe_zet_bronnen_in_het_project(losse_projectmap):
    status = _vraag("project.maak", naam="Twee Clips")
    assert status["naam"] == "twee-clips"

    bron = losse_projectmap / "ergens-anders"
    bron.mkdir()
    for naam in ("een.mp4", "twee.mp4"):
        (bron / naam).write_bytes(b"niet echt video, wel een .mp4")

    uit = _vraag("project.voegtoe", project="twee-clips", paden=[str(bron / "een.mp4"),
                                                                str(bron / "twee.mp4")])
    assert [b["soort"] for b in uit["bestanden"]] == ["video", "video"]
    assert uit["status"]["aantal_clips"] == 2
    # Regel 4: het bronbestand blijft onaangeroerd op zijn eigen plek staan.
    assert (bron / "een.mp4").exists()
    assert (paths.PROJECTEN / "twee-clips" / "bronnen" / "een.mp4").exists()


def test_voegtoe_weigert_een_tekstbestand(losse_projectmap):
    _vraag("project.maak", naam="proef")
    (losse_projectmap / "lijst.txt").write_text("geen video")
    uit = _vraag("project.voegtoe", project="proef", paden=[str(losse_projectmap / "lijst.txt")])
    assert "wordt niet ondersteund" in uit["bestanden"][0]["fout"]
    assert uit["status"]["aantal_clips"] == 0


def test_clip_zet_bewaart_de_keuze_tussen_aanroepen(losse_projectmap):
    _vraag("project.maak", naam="keuze")
    uit = _vraag("clip.zet", project="keuze", clip="een.mp4", aan=False)
    assert uit["aan"] is False
    assert projecten_mod.selectie("keuze") == {"een.mp4"}
    assert _vraag("clip.zet", project="keuze", clip="een.mp4", aan=True)["aan"] is True
    assert projecten_mod.selectie("keuze") == set()


def test_verwerk_zonder_project_is_een_fout_geen_crash(losse_projectmap):
    antwoord = rpc.verwerk('{"id": 2, "methode": "project.verwerk", "params": {}}')
    assert "ontbreekt" in antwoord["fout"]["bericht"]


@nodig_ffmpeg
def test_verwerk_meldt_voortgang_en_klaar_en_levert_clips_met_beeldje(
    losse_projectmap, opgevangen
):
    _vraag("project.maak", naam="motor")
    bron = losse_projectmap / "camera"
    bron.mkdir()
    paden = []
    for naam in ("clip-a.mp4", "clip-b.mp4"):
        _maak_clip(bron / naam)
        paden.append(str(bron / naam))
    _vraag("project.voegtoe", project="motor", paden=paden)

    # Nog niets ingelezen: de lijst moet er toch al staan, uit ffprobe.
    vooraf = _vraag("project.clips", project="motor")
    assert len(vooraf) == 2
    assert all(c["id"] is None and c["score"] is None for c in vooraf)

    assert _vraag("project.verwerk", project="motor", stijl="landschap") == {"gestart": True}

    grens = time.monotonic() + 180
    while time.monotonic() < grens:
        if any(r.get("gebeurtenis") in ("klaar", "fout") for r in opgevangen):
            break
        time.sleep(0.2)

    soorten = [r["gebeurtenis"] for r in opgevangen]
    fouten = [r for r in opgevangen if r["gebeurtenis"] == "fout"]
    assert not fouten, fouten
    assert "klaar" in soorten, f"geen klaar-gebeurtenis; wel: {soorten}"

    voortgang = [r["data"] for r in opgevangen if r["gebeurtenis"] == "voortgang"]
    assert {"inlezen", "analyseren"} <= {d["stap"] for d in voortgang}
    assert all({"project", "stap", "gedaan", "totaal", "tekst"} <= set(d) for d in voortgang)
    # De teller komt uit de logregels "[1/2] C01" van ingest en analyse.
    assert any(d["totaal"] == 2 and d["gedaan"] > 0 for d in voortgang)

    # De tijdschatting rijdt mee: verstreken loopt op, en de klus wordt in
    # seconden bronvideo geteld (2 clips van 2 s) en niet in bestanden.
    assert all({"verstreken", "resterend", "aandeel", "bron_totaal"} <= set(d) for d in voortgang)
    assert max(d["verstreken"] for d in voortgang) > 0
    inlezen = [d for d in voortgang if d["stap"] == "inlezen" and d["bron_totaal"] > 0]
    assert inlezen, "inlezen meldde geen bronvideo"
    assert 3.5 < inlezen[-1]["bron_totaal"] < 4.5, inlezen[-1]["bron_totaal"]

    clips = _vraag("project.clips", project="motor")
    assert [c["naam"] for c in clips] == ["clip-a.mp4", "clip-b.mp4"]
    for c in clips:
        assert c["id"].startswith("C")
        assert c["aan"] is True
        assert 1.8 < c["duur"] < 2.2
        assert (c["breedte"], c["hoogte"]) == (320, 240)
        assert c["fps"] == pytest.approx(30, abs=0.1)
        assert c["thumbnail"] and Path(c["thumbnail"]).stat().st_size > 0

    # Score pas na de analyse, en alleen als er een bruikbaar segment uit kwam.
    analyse = json.loads((paths.PROJECTEN / "motor" / "analysis.json").read_text())
    if analyse.get("segmenten"):
        assert any(c["score"] is not None for c in clips)

    # Een clip uitzetten verandert de lijst, niets anders.
    _vraag("clip.zet", project="motor", clip="clip-a.mp4", aan=False)
    opnieuw = _vraag("project.clips", project="motor")
    assert [c["aan"] for c in opnieuw] == [False, True]


def test_verwerk_start_niets_tweede_keer_maar_boekt_een_ronde_bij(losse_projectmap):
    """Twee keer klikken mag geen twee ingests over elkaar heen starten.

    Het mag ook niet stil verdwijnen: wie tijdens het verwerken clips
    toevoegt, hoort ze in de analyse terug te zien. De engine boekt daarom een
    ronde bij \u2014 eerst deed de interface dat, en die kon de tijdschatting
    alleen opnieuw laten beginnen.
    """
    projecten_mod.zet_bezig("bezet", "Beelden inlezen\u2026")
    try:
        projecten_mod._draaiend.add("bezet")
        uit = _vraag("project.verwerk", project="bezet")
        assert uit == {"gestart": False, "bezig": "Beelden inlezen\u2026", "ingepland": True}
        assert "bezet" in projecten_mod._nogmaals
    finally:
        projecten_mod.zet_bezig("bezet", None)
        projecten_mod._nogmaals.discard("bezet")
        projecten_mod._draaiend.discard("bezet")


@nodig_ffmpeg
def test_clips_toevoegen_tijdens_het_verwerken_komen_in_de_analyse(
    losse_projectmap, opgevangen
):
    """De bijgeboekte ronde moet de nieuwe clip echt oppakken.

    De eerste ronde legt de bronlijst vast bij de start; een clip die daarna
    binnenkomt zat er niet in. Zonder tweede ronde staat hij wel in de lijst en
    nergens in `analysis.json` \u2014 precies de fout die iemand pas ziet als zijn
    beste shot ontbreekt in de montage.
    """
    _vraag("project.maak", naam="bijboeken")
    bron = losse_projectmap / "kaart"
    bron.mkdir()
    for naam in ("een.mp4", "twee.mp4"):
        _maak_clip(bron / naam)
    _vraag("project.voegtoe", project="bijboeken", paden=[str(bron / "een.mp4")])

    assert _vraag("project.verwerk", project="bijboeken") == {"gestart": True}
    # Meteen erachteraan: de ronde loopt nog, dus dit hoort te worden bijgeboekt.
    _vraag("project.voegtoe", project="bijboeken", paden=[str(bron / "twee.mp4")])
    tweede = _vraag("project.verwerk", project="bijboeken")
    assert tweede["gestart"] is False and tweede["ingepland"] is True

    grens = time.monotonic() + 240
    while time.monotonic() < grens:
        if any(r.get("gebeurtenis") in ("klaar", "fout") for r in opgevangen):
            break
        time.sleep(0.2)
    fouten = [r for r in opgevangen if r["gebeurtenis"] == "fout"]
    assert not fouten, fouten
    assert any(r["gebeurtenis"] == "klaar" for r in opgevangen), "nooit klaar geworden"

    # Twee rondes, niet één: "Analyseren…" staat er per ronde één keer. Zonder
    # deze controle zou de test ook groen zijn als de eerste ronde de tweede
    # clip toevallig nog meepakte, en dan bewijst hij niets.
    voortgang = [r["data"] for r in opgevangen if r["gebeurtenis"] == "voortgang"]
    assert sum(1 for d in voortgang if d["tekst"] == "Analyseren…") == 2

    analyse = json.loads((paths.PROJECTEN / "bijboeken" / "analysis.json").read_text())
    assert {c["bestand"] for c in analyse["clips"]} == {"een.mp4", "twee.mp4"}


def test_twee_bronnen_met_dezelfde_naam_overschrijven_elkaar_niet(losse_projectmap):
    """Twee kaartjes uit dezelfde camera leveren allebei een IMG_0001.MOV."""
    _vraag("project.maak", naam="kaarten")
    eerste = losse_projectmap / "kaart-a"
    tweede = losse_projectmap / "kaart-b"
    for m, inhoud in ((eerste, b"beelden van kaart A"), (tweede, b"andere beelden, kaart B")):
        m.mkdir()
        (m / "IMG_0001.MOV").write_bytes(inhoud)

    uit = _vraag(
        "project.voegtoe",
        project="kaarten",
        paden=[str(eerste / "IMG_0001.MOV"), str(tweede / "IMG_0001.MOV")],
    )
    namen = [b["naam"] for b in uit["bestanden"]]
    assert namen == ["IMG_0001.MOV", "IMG_0001-2.MOV"], namen
    assert uit["bestanden"][1]["hernoemd_van"] == "IMG_0001.MOV"
    assert uit["status"]["aantal_clips"] == 2

    bronmap = paths.PROJECTEN / "kaarten" / "bronnen"
    assert (bronmap / "IMG_0001.MOV").read_bytes() == b"beelden van kaart A"
    assert (bronmap / "IMG_0001-2.MOV").read_bytes() == b"andere beelden, kaart B"


def test_hetzelfde_bestand_twee_keer_toevoegen_levert_geen_dubbel(losse_projectmap):
    _vraag("project.maak", naam="dubbelop")
    bron = losse_projectmap / "een-kaart"
    bron.mkdir()
    (bron / "clip.mp4").write_bytes(b"precies dezelfde beelden")

    _vraag("project.voegtoe", project="dubbelop", paden=[str(bron / "clip.mp4")])
    uit = _vraag("project.voegtoe", project="dubbelop", paden=[str(bron / "clip.mp4")])
    assert uit["bestanden"][0]["overgeslagen"] == "staat al in het project"
    assert uit["status"]["aantal_clips"] == 1


def test_een_clip_erbij_vraagt_opnieuw_inlezen(losse_projectmap):
    """Zonder deze controle kwamen later toegevoegde clips nooit in de analyse."""
    _vraag("project.maak", naam="erbij")
    pdir = paths.PROJECTEN / "erbij"
    (pdir / "bronnen" / "een.mp4").write_bytes(b"clip een")
    assert projecten_mod.moet_inlezen("erbij") is True

    # Doe alsof de ingest gedraaid heeft op precies die ene clip.
    (pdir / "ingest.json").write_text(json.dumps({"clips": [{"bestand": "een.mp4"}]}))
    assert projecten_mod.moet_inlezen("erbij") is False

    (pdir / "bronnen" / "twee.mp4").write_bytes(b"clip twee")
    assert projecten_mod.moet_inlezen("erbij") is True

    # En ook als er juist een clip weg is.
    (pdir / "bronnen" / "een.mp4").unlink()
    (pdir / "bronnen" / "twee.mp4").unlink()
    assert projecten_mod.moet_inlezen("erbij") is True


def test_een_map_slepen_pakt_de_clips_eruit_ook_uit_submappen(losse_projectmap):
    """Een SD-kaart in het venster slepen moet werken.

    Daar staan de clips in `DCIM/100GOPRO/`, niet in de wortel, en ernaast
    staat van alles wat geen video is. Zonder deze stap kreeg de gebruiker
    "bestand niet gevonden" — en de app liet dat niet eens zien.
    """
    _vraag("project.maak", naam="kaart")
    kaart = losse_projectmap / "SD-KAART"
    (kaart / "DCIM" / "100GOPRO").mkdir(parents=True)
    (kaart / ".Trashes").mkdir()
    for naam in ("GX010001.MP4", "GX010002.MP4"):
        (kaart / "DCIM" / "100GOPRO" / naam).write_bytes(b"niet echt video, wel een .mp4")
    (kaart / "DCIM" / "lees-mij.txt").write_text("geen video")
    (kaart / ".Trashes" / "weg.mp4").write_bytes(b"verborgen, dus niet meenemen")

    uit = _vraag("project.voegtoe", project="kaart", paden=[str(kaart)])
    namen = sorted(b["naam"] for b in uit["bestanden"])
    assert namen == ["GX010001.MP4", "GX010002.MP4"]
    assert uit["status"]["aantal_clips"] == 2


def test_een_lege_map_slepen_geeft_een_fout_in_plaats_van_stilte(losse_projectmap):
    _vraag("project.maak", naam="leeg")
    leeg = losse_projectmap / "geen-video"
    leeg.mkdir()
    (leeg / "notitie.txt").write_text("niks")

    uit = _vraag("project.voegtoe", project="leeg", paden=[str(leeg)])
    assert uit["bestanden"][0]["fout"] == "geen videobestanden in deze map"
    assert uit["status"]["aantal_clips"] == 0


def test_ander_werk_belooft_geen_ronde_die_niemand_oppakt(losse_projectmap):
    """Codex, 04-10-2026: `ingepland: true` terwijl er niets kwam.

    `_bezig` vult zich ook met een render of een hermontage, en die legen de
    wachtrij nooit — alleen de verwerklus doet dat. Loopt er zulk ander werk,
    dan hoort er niets bijgeboekt te worden en niets beloofd.
    """
    projecten_mod.zet_bezig("rendert", "De montage bedenken\u2026")
    try:
        uit = _vraag("project.verwerk", project="rendert")
        assert uit["gestart"] is False
        assert uit["ingepland"] is False
        assert "rendert" not in projecten_mod._nogmaals
    finally:
        projecten_mod.zet_bezig("rendert", None)


@nodig_ffmpeg
def test_een_mislukte_ronde_laat_het_project_niet_op_slot(losse_projectmap, opgevangen):
    """Codex, 04-10-2026: na een fout bleef "FOUT: …" in `_bezig` staan.

    Daarmee weigerde `neem_bezig()` daarna élke render en elke hermontage, hield
    `bezig` de updater tegen, en gaf een nieuwe poging alleen nog
    `gestart: false`. Een project dat faalde is niet bezig; de fout gaat naar
    de interface.
    """
    _vraag("project.maak", naam="valt-om")
    # Geen bronnen: de ingest gooit meteen.
    assert _vraag("project.verwerk", project="valt-om") == {"gestart": True}

    grens = time.monotonic() + 60
    while time.monotonic() < grens:
        if any(r.get("gebeurtenis") == "fout" for r in opgevangen):
            break
        time.sleep(0.1)
    assert any(r["gebeurtenis"] == "fout" for r in opgevangen), "geen foutmelding"

    time.sleep(0.3)
    assert projecten_mod.is_bezig("valt-om") is None, projecten_mod.is_bezig("valt-om")
    assert "valt-om" not in projecten_mod._draaiend
    assert projecten_mod.neem_bezig("valt-om", "renderen"), "project zit nog op slot"
    projecten_mod.zet_bezig("valt-om", None)
