"""Het exportmenu: van keuze naar bestand.

Wat hier bewezen wordt:

1. een combinatie die niet kan is een fout in gewone woorden, geen export die
   stil iets anders wordt;
2. de standaardkeuze is de master zelf — er wordt niets omgezet;
3. er wordt nooit iets overschreven;
4. elke codec die het menu op deze computer aanbiedt levert echt een bestand
   op met de gevraagde maat, beeldsnelheid en geluid.
"""

import subprocess
from pathlib import Path

import pytest
from cve import export, media, paths, voortgang

from test_rpc_project import _vraag, nodig_ffmpeg


def test_de_standaard_is_de_master():
    assert export.Keuze().is_master()
    assert export.lees_keuze({}).is_master()
    assert export.lees_keuze(None).is_master()
    assert not export.lees_keuze({"audio_kbps": 256}).is_master()
    assert not export.lees_keuze({"resolutie": "720"}).is_master()
    # Map en naam veranderen niet wát er gemaakt wordt.
    assert export.lees_keuze({"map": "/ergens", "naam": "film"}).is_master()


@pytest.mark.parametrize("keuze, woord", [
    ({"container": "avi"}, "Bestandsformaat"),
    ({"container": "mp4", "codec": "prores"}, "past niet"),
    ({"container": "mp4", "audio": "flac"}, "past niet"),
    ({"resolutie": "1081"}, "Resolutie"),
    ({"fps": "23"}, "Beeldsnelheid"),
    ({"kwaliteit": "eigen", "bitrate": 0.2}, "bitrate"),
    ({"kwaliteit": "eigen", "bitrate": "veel"}, "getal"),
    ({"audio_kbps": 96}, "Geluidskwaliteit"),
])
def test_wat_niet_kan_is_een_fout_in_gewone_woorden(keuze, woord):
    with pytest.raises(ValueError, match=woord):
        export.lees_keuze(keuze)


def test_de_maat_houdt_de_verhouding_en_is_altijd_even():
    assert export.maat(1920, 1080, "bron") == (1920, 1080)
    assert export.maat(1920, 1080, "720") == (1280, 720)
    # Staand: 1080p betekent de korte zijde, ook hier.
    assert export.maat(1080, 1920, "720") == (720, 1280)
    assert export.maat(1080, 1350, "720") == (720, 900)
    b, h = export.maat(1080, 1350, "540")
    assert b % 2 == 0 and h % 2 == 0


def test_de_bitrate_volgt_maat_kwaliteit_en_codec():
    k = export.Keuze()
    standaard = export.video_bps(k, 1920, 1080, 30)
    assert standaard == int(1920 * 1080 * 30 * 0.15)
    assert export.video_bps(export.Keuze(kwaliteit="hoog"), 1920, 1080, 30) > standaard
    assert export.video_bps(export.Keuze(kwaliteit="klein"), 1920, 1080, 30) < standaard
    assert export.video_bps(export.Keuze(codec="hevc"), 1920, 1080, 30) < standaard
    assert export.video_bps(export.Keuze(resolutie="720"), 1920, 1080, 30) < standaard
    assert export.video_bps(export.Keuze(kwaliteit="eigen", bitrate=20), 1920, 1080, 30) == 20_000_000
    # ProRes trekt zich niets aan van kwaliteit of bitrate.
    hq = export.video_bps(export.Keuze(codec="prores", prores="hq", kwaliteit="klein"), 1920, 1080, 29.97)
    assert hq == pytest.approx(220_000_000, rel=0.01)


def test_een_bestandsnaam_mag_op_windows_en_op_de_mac():
    assert export.veilige_naam('va/ka:n"tie?  2026 ') == "va ka n tie 2026"
    assert export.veilige_naam("...") == ""
    assert export.veilige_naam("") == ""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    naam = "exportproef"
    (tmp_path / naam / "renders").mkdir(parents=True)
    return naam


def test_er_wordt_nooit_iets_overschreven(project, tmp_path):
    uit = tmp_path / "uit"
    uit.mkdir()
    k = export.lees_keuze({"map": str(uit), "naam": "film"})
    assert export.doelpad(project, k) == uit / "film.mp4"
    (uit / "film.mp4").write_bytes(b"x")
    assert export.doelpad(project, k) == uit / "film-2.mp4"
    (uit / "film-2.mp4").write_bytes(b"x")
    assert export.doelpad(project, k) == uit / "film-3.mp4"
    # Zonder naam heet hij naar het project, zonder map komt hij erbij.
    assert export.doelpad(project, export.lees_keuze({})) == (
        tmp_path / project / "renders" / "export" / f"{project}.mp4"
    )


def test_een_map_die_niet_bestaat_hoor_je_voor_de_render(project, tmp_path):
    k = export.lees_keuze({"map": str(tmp_path / "bestaat-niet")})
    with pytest.raises(ValueError, match="bestaat niet"):
        export.controleer_map(project, k)


def test_een_fase_die_niet_in_de_verdeling_staat_zet_de_balk_niet_op_honderd():
    # De render meldt "look" tussen het samenstellen door. Die fase staat niet
    # in RENDER_FASEN, en dan gaf `plek()` het einde van de balk terug.
    voortgang.start("p", voortgang.RENDER_FASEN)
    voortgang.meld("p", "blokken", 1, 2)
    voor = voortgang.stand("p")["percentage"]
    voortgang.meld("p", "look", 0, 1)
    na = voortgang.stand("p")
    assert na["percentage"] == voor
    assert na["fase"] == "blokken"
    voortgang.wis("p")


def test_de_balk_met_uitvoer_telt_op_tot_honderd():
    fasen = voortgang.render_fasen_met_uitvoer()
    assert fasen[-1][0] == "uitvoer"
    assert sum(g for _, _, g in fasen) == pytest.approx(1.0, abs=1e-3)


def _master(doel: Path, seconden: float = 2.0) -> Path:
    """Een master zoals de render hem maakt: h264, 30 fps, AAC 192k op 48 kHz."""
    naam, opties = media.video_encoder()
    subprocess.run(
        [str(paths.ffmpeg()), "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconden}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconden}",
         "-c:v", naam, *opties, "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-shortest", str(doel)],
        check=True, capture_output=True, timeout=120,
    )
    return doel


@nodig_ffmpeg
def test_de_standaardkeuze_geeft_de_master_zelf_terug(project, tmp_path):
    master = _master(tmp_path / project / "renders" / f"{project}-eind.mp4")
    uit = export.schrijf(project, master, export.lees_keuze({}))
    assert uit["pad"] == str(master)
    assert uit["omgezet"] is False


@nodig_ffmpeg
def test_alleen_een_andere_map_is_een_kopie_zonder_omzetten(project, tmp_path):
    master = _master(tmp_path / project / "renders" / f"{project}-eind.mp4")
    doel = tmp_path / "bureaublad"
    doel.mkdir()
    uit = export.schrijf(project, master, export.lees_keuze({"map": str(doel), "naam": "film"}))
    assert Path(uit["pad"]) == doel / "film.mp4"
    assert Path(uit["pad"]).read_bytes() == master.read_bytes()
    assert uit["omgezet"] is False
    assert not list(doel.glob(".*bezig*")), "het tijdelijke bestand bleef liggen"


def _gevallen():
    # Elke codec en elk geluidsformaat dat het menu kan aanbieden, elk in een
    # formaat waar het in mag. Wat deze computer niet kan valt er in de test af.
    return [
        ({"container": "mp4", "codec": "h264", "kwaliteit": "hoog"}, "h264", "aac"),
        ({"container": "mp4", "codec": "h264", "resolutie": "540", "fps": "25",
          "audio_kbps": 128, "samplerate": 44100}, "h264", "aac"),
        ({"container": "mov", "codec": "h264", "kwaliteit": "eigen", "bitrate": 3,
          "audio": "alac"}, "h264", "alac"),
        ({"container": "mp4", "codec": "hevc", "audio": "geen"}, "hevc", ""),
        ({"container": "mkv", "codec": "hevc", "audio": "flac"}, "hevc", "flac"),
        ({"container": "mov", "codec": "prores", "prores": "lt", "audio": "pcm"},
         "prores", "pcm_s24le"),
        # Alleen het geluid anders: het beeld hoort dan gekopieerd te worden.
        ({"container": "mkv", "codec": "h264", "audio": "pcm"}, "h264", "pcm_s24le"),
    ]


@nodig_ffmpeg
@pytest.mark.parametrize("keuze, codec, geluid", _gevallen())
def test_elke_keuze_levert_het_bestand_dat_gevraagd_is(project, tmp_path, keuze, codec, geluid):
    if keuze["codec"] not in export.beschikbare_codecs():
        pytest.skip(f"{keuze['codec']} kan deze computer niet maken")
    master = _master(tmp_path / project / "renders" / f"{project}-eind.mp4")
    gemeld: list[tuple[float, float]] = []
    k = export.lees_keuze(keuze)
    uit = export.schrijf(project, master, k, voortgang=lambda g, t: gemeld.append((g, t)))

    pad = Path(uit["pad"])
    assert pad.exists() and pad.suffix == f".{keuze['container']}"
    assert pad.parent == tmp_path / project / "renders" / "export"
    assert uit["omgezet"] is True
    assert not list(pad.parent.glob(".*bezig*")), "het tijdelijke bestand bleef liggen"

    info = media.probe(pad)
    assert info.codec == codec
    assert info.audio_codec == geluid
    assert info.heeft_audio is bool(geluid)
    assert (info.breedte, info.hoogte) == export.maat(640, 360, k.resolutie)
    assert info.fps == pytest.approx(30.0 if k.fps == "bron" else float(k.fps), abs=0.01)
    assert info.duur == pytest.approx(2.0, abs=0.15)
    assert gemeld and all(0 <= g <= t for g, t in gemeld)
    # De master blijft wat hij was: `laatste_video` leest alleen renders/*.mp4.
    assert master.exists()


@nodig_ffmpeg
def test_alleen_ander_geluid_kopieert_het_beeld(project, tmp_path):
    master = _master(tmp_path / project / "renders" / f"{project}-eind.mp4")
    k = export.lees_keuze({"container": "mov", "audio_kbps": 256})
    args = export.commando(k, media.probe(master), tmp_path / "x.mov")
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-b:a") + 1] == "256k"
    # En andersom: alleen een ander formaat laat ook het geluid met rust.
    args = export.commando(export.lees_keuze({"container": "mov"}), media.probe(master),
                           tmp_path / "x.mov")
    assert args[args.index("-c:a") + 1] == "copy"


@nodig_ffmpeg
def test_een_mislukte_omzetting_laat_geen_half_bestand_achter(project, tmp_path):
    kapot = tmp_path / project / "renders" / "kapot.mp4"
    kapot.write_bytes(b"dit is geen video")
    with pytest.raises(Exception):
        export.schrijf(project, kapot, export.lees_keuze({"resolutie": "540"}))
    uit = tmp_path / project / "renders" / "export"
    assert not uit.exists() or not list(uit.iterdir())


def test_het_menu_biedt_alleen_aan_wat_kan(project):
    m = _vraag("export.mogelijkheden", project=project)
    kan = {c["id"] for c in m["codecs"] if c["beschikbaar"]}
    assert "h264" in kan, "zonder H.264 is er geen export"
    for c in m["containers"]:
        assert set(c["video"]) <= kan
    for v in m["voorinstellingen"]:
        # Elke voorinstelling moet een keuze zijn die de engine aanneemt.
        export.lees_keuze(v["keuze"])
    assert m["voorinstellingen"][0]["id"] == "standaard"
    assert export.lees_keuze(m["voorinstellingen"][0]["keuze"]).is_master()
    # Zonder montage rekent het menu met het standaardcanvas.
    assert m["bron"]["breedte"] == 1920 and m["resoluties"][0]["id"] == "bron"
    assert all(r["id"] != "1080" for r in m["resoluties"]), "1080p ís de bron al"


def test_de_schatting_noemt_maat_grootte_en_plek(project):
    s = _vraag("export.schat", project=project,
               keuze={"resolutie": "720", "naam": "film", "container": "mov"})
    assert (s["breedte"], s["hoogte"]) == (1280, 720)
    assert s["pad"].endswith("film.mov")
    assert s["omzetten"] is True and s["map_bestaat"] is True
    assert s["video_bps"] == int(1280 * 720 * 30 * 0.15)


def test_alleen_ander_geluid_of_formaat_laat_het_beeld_staan():
    # `maak_video` rendert de master ruimer als er nog een codering achteraan
    # komt. Blijft het beeld staan, dan mag dat níet: dan is de master het
    # eindresultaat en hoort hij de bitrate te hebben die het menu belooft.
    blijft = lambda **kw: export.beeld_blijft(export.Keuze(**kw), 1920, 1080, 30.0)  # noqa: E731
    assert blijft(container="mov")
    assert blijft(audio_kbps=320)
    assert blijft(fps="30"), "30 is de snelheid van de montage zelf"
    assert blijft(resolutie="1080")
    assert not blijft(fps="25")
    assert not blijft(resolutie="720")
    assert not blijft(kwaliteit="hoog")
    assert not blijft(codec="hevc")


def test_de_schatting_wijst_bij_de_standaard_naar_de_master(project):
    s = _vraag("export.schat", project=project, keuze={})
    assert s["omzetten"] is False
    assert s["pad"].endswith(f"renders/{project}-eind.mp4".replace("/", __import__("os").sep))
    assert not (paths.PROJECTEN / project / "renders" / "export").exists()
