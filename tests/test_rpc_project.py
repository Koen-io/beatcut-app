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


def test_verwerk_weigert_als_er_al_iets_loopt(losse_projectmap):
    """Twee keer klikken mag geen twee ingests over elkaar heen starten."""
    projecten_mod.zet_bezig("bezet", "Beelden inlezen\u2026")
    try:
        uit = _vraag("project.verwerk", project="bezet")
        assert uit == {"gestart": False, "bezig": "Beelden inlezen\u2026"}
    finally:
        projecten_mod.zet_bezig("bezet", None)


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
