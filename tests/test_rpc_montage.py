"""Muziek toevoegen en een hele montage maken via het RPC-protocol.

Alles wordt hier zelf gemaakt: twee clips die ffmpeg genereert en een
muziektrack van 20 s op 120 BPM — een lage sinus die elke halve seconde
aantikt (dat is wat een kick is voor een beatdetector) met een melodietje
erover. Zo hangt de test aan niets wat op deze machine toevallig klaarstaat.
"""

import json
import time
from pathlib import Path

import pytest
from cve import montage, paths, projecten as projecten_mod, rpc
from cve.edl import EDL

from test_rpc_project import _vraag, losse_projectmap, nodig_ffmpeg  # noqa: F401

BPM = 120.0
MUZIEK_SECONDEN = 20
CLIP_SECONDEN = 10

# Drie keer `testsrc2`, maar elk anders in beeld. Drie identieke clips
# leveren samen één segment op: de analyse ziet terecht dat het hetzelfde
# beeld is en gooit de dubbele weg. Dan is er niets te monteren.
BEWERKINGEN = ("null", "transpose=1,hue=h=100", "negate,vflip")


def _maak_clip(doel: Path, bewerking: str) -> None:
    import subprocess

    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=480x360:rate=30:duration={CLIP_SECONDEN}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={CLIP_SECONDEN}",
            "-vf", bewerking,
            # mpeg4: zit in elke ffmpeg-build, ook de LGPL-variant die mee gaat
            "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(doel),
        ],
        check=True, capture_output=True, timeout=300,
    )


def _maak_muziek(doel: Path, seconden: int = MUZIEK_SECONDEN) -> None:
    """Een kicktrack op 120 BPM, in WAV zodat elke ffmpeg hem maakt."""
    import subprocess

    tik = 60.0 / BPM  # 0,5 s
    formule = (
        f"0.9*sin(2*PI*60*t)*exp(-9*mod(t,{tik}))"
        f"+0.25*sin(2*PI*440*t)*exp(-2*mod(t,{tik}))"
    )
    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"aevalsrc='{formule}':d={seconden}:s=44100",
            "-c:a", "pcm_s16le", str(doel),
        ],
        check=True, capture_output=True, timeout=120,
    )


@pytest.fixture(scope="module")
def montageproject(tmp_path_factory):
    """Eén project met twee clips, muziek en een gedraaide analyse.

    Module-scope: inlezen en analyseren kost seconden en elke test hier
    begint op precies dezelfde stand.
    """
    if not paths.heeft_ffmpeg():
        pytest.skip("ffmpeg/ffprobe niet gevonden")
    basis = tmp_path_factory.mktemp("montage")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "PROJECTEN", basis / "projecten")
        _vraag("project.maak", naam="montage")

        camera = basis / "camera"
        camera.mkdir()
        paden = []
        for n, bewerking in enumerate(BEWERKINGEN, start=1):
            doel = camera / f"clip-{n}.mp4"
            _maak_clip(doel, bewerking)
            paden.append(str(doel))
        _vraag("project.voegtoe", project="montage", paden=paden)

        _maak_muziek(basis / "track.wav")
        # Rechtstreeks, niet via de RPC: hier gaat het om de uitgangsstand,
        # en op de draad wachten is eerlijker dan op `is_bezig()` pollen —
        # die wordt pas in de werkdraad gezet.
        projecten_mod.verwerk("montage", stijl="reis").join(600)
        assert (paths.PROJECTEN / "montage" / "analysis.json").exists()
        yield "montage", basis


def _zet_muziek(project: str, basis: Path) -> None:
    """Muziek erin en meteen gemeten — zonder werkdraad, zodat de test
    niet op een gebeurtenis hoeft te wachten die niets met hem te maken heeft."""
    montage.zet_muziek(project, str(basis / "track.wav"))
    montage.analyseer_muziek(project)


@pytest.fixture
def opgevangen(monkeypatch):
    regels: list[dict] = []
    monkeypatch.setattr(rpc, "_schrijf", regels.append)
    return regels


def _wacht_op_einde(opgevangen, grens_seconden=600):
    grens = time.monotonic() + grens_seconden
    while time.monotonic() < grens:
        einde = [r for r in opgevangen if r.get("gebeurtenis") in ("klaar", "fout")]
        if einde:
            return einde[0]
        time.sleep(0.2)
    raise AssertionError(f"niets afgerond binnen {grens_seconden} s")


@nodig_ffmpeg
def test_muziek_toevoegen_meet_bpm_en_duur(montageproject, opgevangen):
    project, basis = montageproject
    uit = _vraag("project.muziek", project=project, pad=str(basis / "track.wav"))
    assert uit["bestand"] == "track.wav"

    if uit["gestart"]:
        einde = _wacht_op_einde(opgevangen, 120)
        assert einde["gebeurtenis"] == "klaar", einde
        assert einde["data"]["werk"] == "muziek"
        uit = einde["data"]["muziek"]

    # librosa mag een halve of dubbele maat kiezen; de orde van grootte moet
    # kloppen, en duur en BPM moeten er allebei zijn.
    assert uit["duur"] == pytest.approx(MUZIEK_SECONDEN, abs=0.5)
    assert 50 < uit["bpm"] < 260, uit
    assert min(abs(uit["bpm"] - BPM * f) for f in (0.5, 1, 2)) < 6, uit

    # Regel 4: de bron blijft staan, de kopie staat in het project.
    assert (basis / "track.wav").exists()
    assert (paths.PROJECTEN / project / "muziek" / "track.wav").exists()
    # En de meting zit in analysis.json, niet in een tweede administratie.
    analyse = json.loads((paths.PROJECTEN / project / "analysis.json").read_text())
    assert analyse["muziek"]["bestand"] == "track.wav"
    assert analyse["muziek"]["snijraster"]


@nodig_ffmpeg
def test_muziek_zonder_pad_leest_alleen(montageproject):
    """De interface moet de huidige track kunnen tonen zonder hem te zetten."""
    project, basis = montageproject
    # Een project zonder muziek geeft null, geen fout en geen lege dict.
    _vraag("project.maak", naam="stil")
    assert _vraag("project.muziek", project="stil") is None

    _zet_muziek(project, basis)
    stand = _vraag("project.muziek", project=project)
    assert stand["bestand"] == "track.wav"
    assert stand["bpm"] is not None and stand["duur"] is not None
    # Lezen mag niets verplaatsen: geen tweede track in _vorige/.
    assert not (paths.PROJECTEN / project / "muziek" / "_vorige").exists()


@nodig_ffmpeg
def test_stijlen_noemt_de_vijf_stijlen_en_alleen_vormen_die_werken(montageproject):
    project, _ = montageproject
    uit = _vraag("project.stijlen", project=project)
    namen = [s["naam"] for s in uit["stijlen"]]
    assert namen == ["actie", "landschap", "luchtvaart", "reis", "vlog"]
    assert all(s["titel"] and s["omschrijving"] for s in uit["stijlen"])
    assert uit["herkend"] in namen
    # Alleen wat de renderer echt kan. 4:5 staat niet in `preset.VORMEN` en
    # zou dus stil 16:9 opleveren — daarom bieden we het niet aan.
    assert [v["naam"] for v in uit["vormen"]] == ["16:9", "9:16", "1:1"]
    assert {"naam": "16:9", "breedte": 1920, "hoogte": 1080} in uit["vormen"]


@nodig_ffmpeg
def test_maakvideo_levert_een_mp4_met_het_aantal_frames_uit_de_edl(
    montageproject, opgevangen
):
    project, basis = montageproject
    _zet_muziek(project, basis)
    opgevangen.clear()

    begin = time.monotonic()
    assert _vraag(
        "project.maakvideo", project=project, stijl="reis", vorm="16:9",
        duur=8, kwaliteit="preview",
    ) == {"gestart": True}

    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde
    data = einde["data"]
    print(f"\nmaakvideo preview op 2 clips: {time.monotonic() - begin:.1f} s")

    assert data["werk"] == "maakvideo"
    assert data["project"] == project
    video = Path(data["video"])
    assert video.is_absolute() and video.exists() and video.stat().st_size > 0
    assert data["duur"] > 1
    assert data["uitleg"]

    # Review: elke bevinding met naam, ok en tekst.
    assert data["review"], "geen reviewresultaten"
    assert all({"naam", "ok", "tekst"} <= set(r) for r in data["review"])

    # Voortgang: de stappen van voortgang.py, met een percentage dat oploopt.
    voortgang = [r["data"] for r in opgevangen if r.get("gebeurtenis") == "voortgang"]
    stappen = {d["stap"] for d in voortgang}
    assert {"voorbereiden", "blokken", "nakijken"} <= stappen, stappen
    percentages = [d["percentage"] for d in voortgang]
    assert percentages == sorted(percentages) and percentages[-1] > percentages[0]

    # Het aantal frames moet exact uit de EDL komen: de renderer werkt met
    # `-frames:v N`, nooit met `-t <seconden>` (zie CLAUDE.md).
    from cve.review import _frames

    edl = EDL.lees(paths.PROJECTEN / project / "edl.json")
    verwacht = sum(
        max(1, b.frames or round(b.duur * edl.canvas.fps)) for b in edl.video
    )
    assert _frames(video) == verwacht

    # En `project.video` vindt diezelfde render terug.
    laatste = _vraag("project.video", project=project)
    assert Path(laatste["video"]) == video
    assert laatste["review"] and len(laatste["review"]) == len(data["review"])
    assert laatste["duur"] == pytest.approx(data["duur"], abs=0.2)


@nodig_ffmpeg
def test_twee_keer_maakvideo_tegelijk_geeft_een_nette_fout(montageproject):
    project, _ = montageproject
    assert projecten_mod.neem_bezig(project, "Beelden knippen…")
    try:
        antwoord = rpc.verwerk(json.dumps({
            "id": 9, "methode": "project.maakvideo", "params": {"project": project},
        }))
        assert "Er loopt al werk" in antwoord["fout"]["bericht"]
    finally:
        projecten_mod.zet_bezig(project, None)


@nodig_ffmpeg
@pytest.mark.parametrize("vorm", ["9:16", "1:1"])
def test_de_andere_vormen_renderen_ook(montageproject, opgevangen, vorm):
    """Alleen aanbieden wat een test haalt — dus hier gemeten, niet beloofd."""
    project, basis = montageproject
    _zet_muziek(project, basis)
    opgevangen.clear()
    _vraag("project.maakvideo", project=project, vorm=vorm, duur=4, kwaliteit="preview")
    einde = _wacht_op_einde(opgevangen)
    assert einde["gebeurtenis"] == "klaar", einde

    breedte, hoogte = montage.VORMEN[vorm]
    edl = EDL.lees(paths.PROJECTEN / project / "edl.json")
    assert (edl.canvas.breedte, edl.canvas.hoogte) == (breedte, hoogte)
    # Het beeldformaat van de render zelf wordt door review nagekeken; een
    # fout daarover zou hier als niet-geslaagd terugkomen.
    formaat = [r for r in einde["data"]["review"] if r["naam"] == "canvas"]
    assert formaat and formaat[0]["ok"], einde["data"]["review"]


def test_maakvideo_zonder_analyse_is_een_nette_fout(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    _vraag("project.maak", naam="kaal")
    antwoord = rpc.verwerk(json.dumps({
        "id": 3, "methode": "project.maakvideo", "params": {"project": "kaal"},
    }))
    assert "nog niet geanalyseerd" in antwoord["fout"]["bericht"]


def test_een_onbekende_vorm_wordt_geweigerd_in_plaats_van_stil_169(tmp_path, monkeypatch):
    """4:5 bestaat niet in de renderer; stil terugvallen op 16:9 is erger."""
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    _vraag("project.maak", naam="vormloos")
    antwoord = rpc.verwerk(json.dumps({
        "id": 4, "methode": "project.maakvideo",
        "params": {"project": "vormloos", "vorm": "4:5"},
    }))
    assert "4:5" in antwoord["fout"]["bericht"]


def test_muziek_weigert_een_videobestand(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    _vraag("project.maak", naam="geenmuziek")
    (tmp_path / "clip.mp4").write_bytes(b"geen muziek")
    antwoord = rpc.verwerk(json.dumps({
        "id": 5, "methode": "project.muziek",
        "params": {"project": "geenmuziek", "pad": str(tmp_path / "clip.mp4")},
    }))
    assert "geen muziek" in antwoord["fout"]["bericht"]


def test_een_tweede_track_duwt_de_eerste_naar_vorige(tmp_path, monkeypatch):
    """Vervangen mag nooit iets wegmaken wat niet terug te halen is."""
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    _vraag("project.maak", naam="wisselen")
    for naam in ("een.wav", "twee.wav"):
        (tmp_path / naam).write_bytes(b"RIFF" + naam.encode())
        montage.zet_muziek("wisselen", str(tmp_path / naam))

    mdir = paths.PROJECTEN / "wisselen" / "muziek"
    assert [p.name for p in mdir.glob("*.wav")] == ["twee.wav"]
    assert (mdir / "_vorige" / "een.wav").read_bytes() == b"RIFFeen.wav"


# -- snedes op de tel -------------------------------------------------------

# Dezelfde kicktrack, maar de laatste 6 s is stil. Daarmee stopt `beat_track`
# bij 13,5 s terwijl de track 20 s duurt — precies de situatie waarin de vier
# laatste snedes van de testmontage tot 10,9 s naast de tel lagen: de regie
# snijdt door tot het eind van de muziek, en daar lag geen raster.
UITLOOP_STIL_VANAF = 14


def _maak_muziek_met_stille_uitloop(doel: Path) -> None:
    import subprocess

    tik = 60.0 / BPM
    kick = (
        f"0.9*sin(2*PI*60*t)*exp(-9*mod(t,{tik}))"
        f"+0.25*sin(2*PI*440*t)*exp(-2*mod(t,{tik}))"
    )
    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"aevalsrc='if(lt(t,{UITLOOP_STIL_VANAF}), {kick}, 0)'"
            f":d={MUZIEK_SECONDEN}:s=44100",
            "-c:a", "pcm_s16le", str(doel),
        ],
        check=True, capture_output=True, timeout=120,
    )


@nodig_ffmpeg
def test_snedes_liggen_op_de_tel_ook_in_de_stille_uitloop(montageproject):
    """Elke snede binnen één frame van een tel, over de hele montage.

    Meet op dezelfde manier als `review._controleer_beat`: de tijdlijn plus de
    muziekverschuiving, tegen het tel-raster uit `analysis.json`.
    """
    from cve.director.basis import Brief
    from cve.director.preset import PresetRegisseur

    project, basis = montageproject
    track = basis / "track-uitloop.wav"
    _maak_muziek_met_stille_uitloop(track)
    montage.zet_muziek(project, str(track))
    montage.analyseer_muziek(project)

    analyse = json.loads((paths.PROJECTEN / project / "analysis.json").read_text())
    beats = analyse["muziek"]["beats"]
    duur = analyse["muziek"]["duur"]

    # Het raster moet de hele track dekken. Zonder verlenging houdt het op bij
    # ongeveer 13,5 s en is er in de uitloop niets om op te snijden.
    assert beats[-1] > duur - 2 * (60.0 / BPM), (
        f"telraster stopt bij {beats[-1]:.2f} s van {duur:.2f} s"
    )

    voorstel = PresetRegisseur().stel_voor(analyse, Brief(stijl="reis", vorm="16:9"))
    edl = voorstel.edl
    assert edl.video and edl.audio
    # De montage moet tot in de uitloop doorlopen, anders toetst dit niets.
    assert edl.duur > UITLOOP_STIL_VANAF, edl.duur

    verschuiving = edl.audio[0].bron_start
    een_frame_ms = 1000.0 / edl.canvas.fps
    naast = []
    for blok in edl.video[1:]:
        t = blok.tijdlijn_start + verschuiving
        afwijking = abs(min(beats, key=lambda b: abs(b - t)) - t) * 1000.0
        if afwijking > een_frame_ms:
            naast.append((blok.id, round(blok.tijdlijn_start, 3), round(afwijking, 1)))
    assert not naast, f"snedes naast de tel (>{een_frame_ms:.1f} ms): {naast}"


# --------------------------------------------------------------------------
# Muziek wisselen: wat er met de oude gebeurt, en wanneer de meting vervalt
# --------------------------------------------------------------------------


def test_archief_van_vorige_muziek_overschrijft_niets(losse_projectmap, tmp_path):
    """Drie keer een bestand dat `song.wav` heet, zijn drie nummers.

    `_vorige/` was de enige plek waar de eerste twee nog stonden, en een
    vaste naam gooide ze er allebei weer uit.
    """
    _vraag("project.maak", naam="wisselen")
    for n, inhoud in enumerate((b"een", b"twee", b"drie")):
        bron = tmp_path / f"bron{n}"
        bron.mkdir()
        (bron / "song.wav").write_bytes(inhoud)
        montage.zet_muziek("wisselen", str(bron / "song.wav"))

    vorige = paths.project_dir("wisselen") / "muziek" / "_vorige"
    assert sorted(q.read_bytes() for q in vorige.iterdir()) == [b"een", b"twee"]
    assert (paths.project_dir("wisselen") / "muziek" / "song.wav").read_bytes() == b"drie"


@nodig_ffmpeg
def test_meting_vervalt_bij_andere_muziek_met_dezelfde_naam(losse_projectmap, tmp_path):
    """De cache mag niet op de bestandsnaam alleen sleutelen.

    Wie `track.wav` vervangt door een ander nummer met dezelfde naam, hield
    anders de beats, de BPM en de duur van het oude — en dan ligt de montage
    op beats die er niet meer zijn.
    """
    _vraag("project.maak", naam="cache")
    pdir = paths.project_dir("cache")
    pdir.joinpath("analysis.json").write_text(json.dumps({"clips": []}), encoding="utf-8")

    lang = tmp_path / "lang" / "track.wav"
    lang.parent.mkdir()
    _maak_muziek(lang, seconden=20)
    montage.zet_muziek("cache", str(lang))
    eerst = montage.analyseer_muziek("cache")
    assert eerst["duur"] > 15

    kort = tmp_path / "kort" / "track.wav"
    kort.parent.mkdir()
    _maak_muziek(kort, seconden=8)
    montage.zet_muziek("cache", str(kort))

    assert montage.muziekstand("cache") is None, "de oude meting wordt hergebruikt"
    assert montage.analyseer_muziek("cache")["duur"] < 10


# --------------------------------------------------------------------------
# Montagestijlen: veertien ritmes, allemaal op de tel
# --------------------------------------------------------------------------


def _afwijking_van_de_tel(edl, beats: list[float]) -> float:
    """Grootste afstand van een snede tot de dichtstbijzijnde tel, in ms.

    Zelfde meting als `review._controleer_beat`: tijdlijntijd plus de
    verschuiving van het audiospoor, want daar begint de montage in de muziek.
    """
    verschuiving = edl.audio[0].bron_start if edl.audio else 0.0
    return max(
        (
            abs(min(beats, key=lambda b: abs(b - (blok.tijdlijn_start + verschuiving)))
                - (blok.tijdlijn_start + verschuiving)) * 1000.0
            for blok in edl.video[1:]
        ),
        default=0.0,
    )


def test_elke_montagestijl_is_geldig_en_rendert_alleen_wat_kan():
    """Veertien stijlen, energie 1..5, en geen overgang die de renderer niet kan.

    De vaste lijst staat in `edl.OVERGANGEN`, maar niet alles daarin kan de
    ffmpeg-keten al (whip-pan, glitch, RGB-split wachten op de compositor).
    `montagestijl.laad()` moet zoiets omzetten in een snede mét waarschuwing —
    een stille terugval zou betekenen dat de kaart iets belooft wat niet komt.
    """
    from cve import montagestijl

    stijlen = montagestijl.alle(paths.STYLES)
    assert len(stijlen) == 14, [m.id for m in stijlen]
    # De vaste volgorde is snel naar rustig; dat is wat de interface toont.
    assert [m.energie for m in stijlen] == sorted(
        (m.energie for m in stijlen), reverse=True
    ), [(m.id, m.energie) for m in stijlen]
    for m in stijlen:
        assert 1 <= m.energie <= 5, m.id
        assert m.titel and m.omschrijving, m.id
        assert m.patroon and all(p > 0 for p in m.patroon), m.id
        assert not m.waarschuwingen, m.waarschuwingen
        for naam in m.overgangen:
            assert naam in montagestijl.kan_renderen(), (m.id, naam)


def test_onbekende_overgang_wordt_een_snede_met_waarschuwing(tmp_path, monkeypatch):
    """Zonder compositor: `whip_pan` wordt een snede met waarschuwing; met
    compositor gaat hij gewoon door. Een verzonnen naam is altijd een snede."""
    from cve import compositor, montagestijl

    (tmp_path / "montage").mkdir()
    (tmp_path / "montage" / "proef.md").write_text(
        "# Proef\n\nEen stijl die iets vraagt.\n\n"
        "```yaml montage\nenergie: 5\npatroon: 1\novergangen: snede whip_pan bestaatniet\n"
        "overgang_elke: 2\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compositor, "aan", lambda: False)
    m = montagestijl.laad("proef", tmp_path)
    assert m.overgangen == ["snede", "snede", "snede"]
    assert any("compositor" in w for w in m.waarschuwingen), m.waarschuwingen
    assert any("bestaat niet" in w for w in m.waarschuwingen), m.waarschuwingen
    assert m.overgang_voor(2) == ("snede", 0.0)

    monkeypatch.setattr(compositor, "aan", lambda: True)
    m = montagestijl.laad("proef", tmp_path)
    assert m.overgangen == ["snede", "whip_pan", "snede"]
    assert m.overgang_voor(2)[0] == "whip_pan"


@nodig_ffmpeg
def test_alle_montagestijlen_snijden_op_de_tel_en_in_hun_eigen_ritme(montageproject):
    """Per montagestijl: snedes op de tel, shotlengte volgens het patroon.

    Twee dingen worden getoetst. Eén: elke snede ligt binnen één frame van een
    gedetecteerde tel — dat is de belofte van de hele app. Twee: de gemeten
    shotlengte in tellen past bij het patroon van die stijl, en de rustige
    stijlen snijden dus echt langzamer dan de snelle.

    Het plafond rekenen we hier zelf uit, net als de regisseur: een shot kan
    niet langer zijn dan het langste bruikbare stuk beeld. Op drie testclips
    van tien seconden kan Ambient (zestien tellen) daar tegenaan lopen, en dan
    is een ingekort patroon het goede antwoord en geen fout.
    """
    from cve import montagestijl
    from cve.director.basis import Brief
    from cve.director.preset import PresetRegisseur

    project, basis = montageproject
    _zet_muziek(project, basis)
    analyse = json.loads((paths.PROJECTEN / project / "analysis.json").read_text())
    beats = analyse["muziek"]["beats"]
    tel = 60.0 / analyse["muziek"]["bpm"]
    langste = max(s["duur"] for s in analyse["segmenten"])
    plafond = max(1, int(langste * 0.95 / tel))

    gemeten: list[tuple[str, float]] = []
    for m in montagestijl.alle(paths.STYLES):
        voorstel = PresetRegisseur().stel_voor(
            analyse, Brief(stijl="reis", montage=m.id, vorm="16:9")
        )
        edl = voorstel.edl
        edl.valideer()
        assert len(edl.video) >= 2, (m.id, voorstel.waarschuwingen)

        een_frame_ms = 1000.0 / edl.canvas.fps
        afwijking = _afwijking_van_de_tel(edl, beats)
        assert afwijking <= een_frame_ms, (
            f"{m.id}: snede {afwijking:.1f} ms naast de tel (max {een_frame_ms:.1f})"
        )

        tellen = sum(b.duur for b in edl.video) / len(edl.video) / tel
        # Waar het patroon op dit materiaal past, moet het ook gevolgd worden.
        verwacht = sum(min(p, plafond) for p in m.patroon) / len(m.patroon)
        assert abs(tellen - verwacht) <= max(0.5, 0.3 * verwacht), (
            f"{m.id}: {tellen:.2f} tellen gemeten, {verwacht:.2f} verwacht "
            f"(patroon {m.patroon}, plafond {plafond})"
        )
        gemeten.append((m.id, tellen))

    # Snel moet echt sneller zijn dan rustig, over de hele reeks.
    snelste, rustigste = gemeten[0], gemeten[-1]
    assert snelste[1] < rustigste[1], (snelste, rustigste)
    assert dict(gemeten)["velocity"] < dict(gemeten)["cine"] < dict(gemeten)["stilte"], gemeten


@nodig_ffmpeg
def test_een_andere_montagestijl_vraagt_een_nieuwe_regie(montageproject):
    """`regie_nodig()` moet de montagestijl meewegen.

    Zonder dat zou "Maak video" na het wisselen van Velocity naar Stilte de
    oude montage opnieuw renderen: andere kaart gekozen, zelfde beeld.
    """
    project, _ = montageproject
    brief = montage.brief_van("reis", "16:9", None, "velocity")
    assert brief["montage"] == "velocity"
    # Leeg laten betekent: de montagestijl die bij dit soort beelden hoort.
    assert montage.brief_van("reis", "16:9", None)["montage"] == "cine"

    edlpad = paths.project_dir(project) / "edl.json"
    if not edlpad.exists():
        pytest.skip("nog geen montage in dit project")
    edl = EDL.lees(edlpad)
    edl.brief = brief
    edl.schrijf(edlpad)
    assert not montage.regie_nodig(
        project, stijl="reis", vorm="16:9", duur=None, montage="velocity"
    )
    assert montage.regie_nodig(
        project, stijl="reis", vorm="16:9", duur=None, montage="stilte"
    )
