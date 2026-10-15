"""Spraak in de BeatCut 2-route (13-10-2026): ondertitels, eigen geluid, ducking.

Drie lagen:
1. de wiskunde van `transcript.op_tijdlijn` bij een andere snelheid;
2. `spraak._leg_op` zonder whisper (transcript nagebootst): overlay erin,
   geluid aan op pratende shots, `weg` haalt alles weer weg, `herleg` na regie;
3. eind-tot-eind met échte spraak: macOS `say` maakt een clip met een zin,
   whisper.cpp herkent hem, en de render bevat de ondertitellaag.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from cve import paths, spraak, transcript
from cve.edl import EDL, VideoBlok
from cve.transcript import Woord

from test_rpc_bijwerken import gemonteerd  # noqa: F401
from test_rpc_montage import _wacht_op_einde, _zet_muziek, montageproject, opgevangen  # noqa: F401
from test_rpc_project import _maak_clip, _vraag, nodig_ffmpeg


def _edl(*blokken) -> EDL:
    return EDL(project="p", video=[VideoBlok(id=f"v{i}", **b) for i, b in enumerate(blokken)])


def test_woorden_schalen_mee_met_de_snelheid(tmp_path, monkeypatch):
    woorden = [Woord("een", 2.0, 2.4), Woord("twee", 3.0, 3.4), Woord("drie", 9.0, 9.4)]
    monkeypatch.setattr(transcript, "transcribeer_clip", lambda *a, **k: woorden)
    (tmp_path / "bronnen").mkdir()
    (tmp_path / "bronnen" / "a.mp4").write_bytes(b"x")
    # Shot van 2 s tijdlijn op 2x: bron 1..5. "een" op bron 2,0 → tijdlijn 10 + 0,5.
    edl = _edl(dict(clip="C01", bestand="a.mp4", bron_start=1.0, duur=2.0,
                    tijdlijn_start=10.0, snelheid=2.0))
    uit = transcript.op_tijdlijn(edl, tmp_path, log=lambda *_: None)
    assert [(w.tekst, w.start, w.eind) for w in uit] == [
        ("een", 10.5, 10.7), ("twee", 11.0, 11.2),
    ]
    # Een woord dat over de snede heen loopt hoort bij het shot waarin het
    # begint en wordt op de snede geklemd; wat vóór het shot begint niet.
    monkeypatch.setattr(
        transcript, "transcribeer_clip",
        lambda *a, **k: [Woord("vooraf", 0.5, 1.2), Woord("over", 4.8, 5.6)],
    )
    uit = transcript.op_tijdlijn(edl, tmp_path, log=lambda *_: None)
    assert [(w.tekst, w.start, w.eind) for w in uit] == [("over", 11.9, 12.0)]


def test_begrens_houdt_whisper_binnen_de_clip_en_binnen_elkaar():
    w = [Woord("a", 0.0, 1.9), Woord("b", 1.9, 2.84), Woord("c", 6.03, 30.0)]
    uit = transcript._begrens(w, 6.5)
    assert [(x.start, x.eind) for x in uit] == [(0.0, 1.5), (1.9, 2.84), (6.03, 6.5)]
    assert transcript._begrens([], None) == []
    # Een gaatje van 0,2 s gaat dicht, een pauze van 0,5 s niet.
    uit = transcript._begrens([Woord("a", 0.0, 0.3), Woord("b", 0.5, 0.7), Woord("c", 1.2, 1.4)], None)
    assert [(x.start, x.eind) for x in uit] == [(0.0, 0.5), (0.5, 0.7), (1.2, 1.4)]


def test_woorden_uit_tokens_plakt_stukjes_en_leestekens_aan_elkaar():
    """De vorm van whispers `--output-json-full` (14-10-2026 nagemeten)."""
    def tok(t, van, tot):
        return {"text": t, "offsets": {"from": van, "to": tot}}

    d = {"transcription": [{"tokens": [
        tok("[_BEG_]", 0, 0), tok(" Hallo", 30, 280), tok(" allemaal", 280, 730), tok(",", 730, 840),
        tok(" on", 1900, 2010), tok("dert", 2010, 2230), tok("itels", 2230, 2460), tok(" .", 2460, 2500),
        tok("[_TT_123]", 2500, 2500),
    ]}]}
    uit = transcript.woorden_uit_tokens(d)
    assert [(w.tekst, w.start, w.eind) for w in uit] == [
        ("Hallo", 0.03, 0.28), ("allemaal,", 0.28, 0.84), ("ondertitels.", 1.9, 2.5),
    ]


def test_een_oude_cache_wordt_opnieuw_gemaakt(tmp_path, monkeypatch):
    """Caches van vóór versie 2 hebben de scheve `-ml 1`-tijden."""
    (tmp_path / "transcript").mkdir()
    (tmp_path / "transcript" / "a.json").write_text('{"bestand": "a.mp4", "woorden": [{"tekst": "x", "start": 0, "eind": 1}]}')
    monkeypatch.setattr(paths, "whisper_bin", lambda: None)
    with pytest.raises(transcript.TranscriptFout):
        transcript.transcribeer_clip(tmp_path / "a.mp4", tmp_path)
    (tmp_path / "transcript" / "a.json").write_text(
        '{"versie": 2, "bestand": "a.mp4", "woorden": [{"tekst": "x", "start": 0, "eind": 1}]}')
    assert transcript.transcribeer_clip(tmp_path / "a.mp4", tmp_path)[0].tekst == "x"


def test_leg_op_zet_overlay_en_geluid_en_weg_haalt_ze_weer_weg(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    pdir = tmp_path / "p"
    (pdir / "bronnen").mkdir(parents=True)
    for n in ("a.mp4", "b.mp4"):
        (pdir / "bronnen" / n).write_bytes(b"x")
    per = {"a.mp4": [Woord("hallo", 0.5, 0.9), Woord("daar", 1.0, 1.3)], "b.mp4": []}
    monkeypatch.setattr(transcript, "transcribeer_clip", lambda bron, *a, **k: per[bron.name])

    edl = _edl(
        dict(clip="C01", bestand="a.mp4", bron_start=0.0, duur=2.0, tijdlijn_start=0.0, reden="r1"),
        dict(clip="C02", bestand="b.mp4", bron_start=0.0, duur=2.0, tijdlijn_start=2.0, reden="r2"),
    )
    edl.audio = []
    data = spraak._leg_op(edl, pdir, dict(spraak.STANDAARD, aan=True), log=lambda *_: None)
    assert data["aantal_woorden"] == 2
    assert (pdir / "ondertitels.json").exists()
    assert [o.soort for o in edl.overlay] == ["ondertitels"]
    assert edl.overlay[0].inhoud["stijl"] == "karaoke"
    a, b = edl.video
    assert a.geluid == spraak.GELUID and a.geluid_na == spraak.L_CUT and a.geluid_voor == 0.0
    assert a.reden.endswith("· spraak")
    assert b.geluid == 0.0 and b.reden == "r2"

    edl.schrijf(pdir / "edl.json")
    spraak._schrijf_instellingen("p", dict(spraak.STANDAARD, aan=True))
    assert spraak.stand("p")["aan"] is True and spraak.stand("p")["woorden"] == 2

    # Herleggen na een "nieuwe regie" waarin a nu op 2x staat.
    edl.video[0].snelheid = 2.0
    spraak.herleg(edl, pdir)
    assert edl.video[0].geluid == spraak.GELUID

    uit = spraak.weg("p")
    assert uit["aan"] is False and uit["woorden"] == 0
    na = EDL.lees(pdir / "edl.json")
    assert na.overlay == [] and all(v.geluid == 0.0 for v in na.video)
    assert na.video[0].reden == "r1"
    # Uit: herleggen doet niets meer.
    spraak.herleg(na, pdir)
    assert na.overlay == []


def test_herleg_laat_een_montage_heel_als_het_transcript_faalt(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path)
    pdir = tmp_path / "p"
    pdir.mkdir()
    spraak._schrijf_instellingen("p", dict(spraak.STANDAARD, aan=True))

    def kapot(*a, **k):
        raise RuntimeError("whisper weg")

    monkeypatch.setattr(transcript, "op_tijdlijn", kapot)
    edl = _edl(dict(clip="C01", bestand="a.mp4", bron_start=0.0, duur=2.0, tijdlijn_start=0.0))
    spraak.herleg(edl, pdir)
    assert len(edl.video) == 1


# -- eind-tot-eind met echte spraak -------------------------------------------

nodig_say = pytest.mark.skipif(shutil.which("say") is None, reason="macOS `say` niet gevonden")
nodig_whisper = pytest.mark.skipif(
    paths.whisper_bin() is None or paths.whisper_model() is None, reason="whisper.cpp ontbreekt"
)


def _maak_spraakclip(doel: Path, tekst: str, seconden: int = 6) -> None:
    """Een clip met gesproken tekst, en een ánder beeld dan de andere testclips:
    `testsrc2` is overal hetzelfde patroon en dan ontdubbelt de analyse de
    spraakclip weg als kopie van een beter segment."""
    aiff = doel.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Xander", "-o", str(aiff), tekst], check=True, timeout=60)
    subprocess.run(
        [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"smptehdbars=size=320x240:rate=30:duration={seconden}",
         "-i", str(aiff), "-af", "apad", "-t", str(seconden),
         "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-c:a", "aac", str(doel)],
        check=True, capture_output=True, timeout=120,
    )


@nodig_ffmpeg
@nodig_say
@nodig_whisper
def test_echte_spraak_wordt_herkend_en_komt_in_edl_en_render(gemonteerd, opgevangen):  # noqa: F811
    project, basis = gemonteerd
    # Eén clip met spraak erbij, dan opnieuw regisseren zodat hij meedoet.
    bron = basis / "camera" / "praat.mp4"
    _maak_spraakclip(bron, "Dit is een proef met gesproken tekst voor de ondertitels.")
    _vraag("project.voegtoe", project=project, paden=[str(bron)])
    opgevangen.clear()  # de fixture liet al een `klaar` achter
    _vraag("project.verwerk", project=project, stijl="vlog")
    einde = _wacht_op_einde(opgevangen)
    assert einde and einde["gebeurtenis"] == "klaar", einde
    opgevangen.clear()
    from cve import bijwerken

    bijwerken.zet_voorkeur(project, "praat.mp4", "moet")
    _vraag("project.regisseer", project=project, stijl="vlog", montage="vlog", vorm="16:9", duur=8.0)

    assert _vraag("spraak.stand", project=project)["kan"] is True
    assert _vraag("spraak.maak", project=project) == {"gestart": True}
    grens = time.monotonic() + 300
    while time.monotonic() < grens and not any(
        r.get("gebeurtenis") in ("klaar", "fout") and r["data"].get("werk") == "spraak"
        for r in opgevangen
    ):
        time.sleep(0.3)
    einde = [r for r in opgevangen if r["data"].get("werk") == "spraak" and r["gebeurtenis"] in ("klaar", "fout")]
    assert einde and einde[0]["gebeurtenis"] == "klaar", einde
    # Whisper geeft op kunstmatige spraak grove woordtijden; de montage
    # gebruikt drie van de zes seconden. Eén herkend woord is het bewijs.
    assert einde[0]["data"]["woorden"] >= 1, einde[0]

    stand = _vraag("spraak.stand", project=project)
    assert stand["aan"] is True and stand["regels"] >= 1
    pdir = paths.PROJECTEN / project
    edl = EDL.lees(pdir / "edl.json")
    assert any(o.soort == "ondertitels" for o in edl.overlay)
    pratend = [b for b in edl.video if b.bestand == "praat.mp4"]
    assert pratend and all(b.geluid > 0 for b in pratend)
    regels = json.loads((pdir / "ondertitels.json").read_text())["regels"]
    tekst = " ".join(r["tekst"] for r in regels).lower()
    assert any(w in tekst for w in ("dit", "is", "een", "proef", "tekst", "ondertitel")), tekst

    # Opnieuw regisseren houdt spraak vast.
    _vraag("project.regisseer", project=project, stijl="vlog", montage="vlog", vorm="16:9", duur=8.0)
    weer = EDL.lees(pdir / "edl.json")
    assert any(o.soort == "ondertitels" for o in weer.overlay)
