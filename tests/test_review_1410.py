"""Bevindingen van de review van 14-10-2026 (Codex had een gebruikslimiet;
een tweede, onafhankelijke Claude-reviewer las de drie commits na).

- de taalkeuze van spraak deed niets (niet doorgegeven, niet in de cache-sleutel);
- na verplaatsen/trimmen/zet_shot bleven de ondertitels op de oude tijden;
- zet_shot schreef onder een lopende spraak-werkdraad door;
- een andere snelheid stemde de kleur niet opnieuw af.
"""

import json

import pytest
from cve import bijwerken, monteren, paths, projecten, spraak, transcript
from cve.edl import EDL
from cve.transcript import Woord

from test_rpc_bijwerken import gemonteerd  # noqa: F401
from test_rpc_montage import montageproject, opgevangen  # noqa: F401
from test_rpc_project import nodig_ffmpeg


def test_de_taal_hoort_bij_de_transcriptcache(tmp_path, monkeypatch):
    (tmp_path / "transcript").mkdir()
    (tmp_path / "transcript" / "a.json").write_text(json.dumps(
        {"versie": transcript.CACHE_VERSIE, "bestand": "a.mp4",
         "woorden": [{"tekst": "x", "start": 0, "eind": 1}]}))
    monkeypatch.setattr(paths, "whisper_bin", lambda: None)
    # Zonder taal in de cache: gemaakt met "auto", dus "auto" leest hem...
    assert transcript.transcribeer_clip(tmp_path / "a.mp4", tmp_path)[0].tekst == "x"
    # ...maar "nl" moet opnieuw transcriberen (en faalt hier: geen whisper).
    with pytest.raises(transcript.TranscriptFout):
        transcript.transcribeer_clip(tmp_path / "a.mp4", tmp_path, taal="nl")


def test_leg_op_geeft_de_gekozen_taal_door(tmp_path, monkeypatch):
    gezien = []

    def nep(bron, cache, *, taal="auto", log=print):
        gezien.append(taal)
        return []

    monkeypatch.setattr(transcript, "transcribeer_clip", nep)
    (tmp_path / "bronnen").mkdir()
    (tmp_path / "bronnen" / "a.mp4").write_bytes(b"x")
    from cve.edl import VideoBlok

    edl = EDL(project="p", video=[VideoBlok(id="v0", clip="C01", bestand="a.mp4",
                                            bron_start=0.0, duur=2.0, tijdlijn_start=0.0)])
    spraak._leg_op(edl, tmp_path, dict(spraak.STANDAARD, aan=True, taal="nl"), log=lambda *_: None)
    assert gezien == ["nl"]


def _nep_transcript(monkeypatch):
    """Elke clip zegt elke seconde zijn eigen naam: zo is te zien welk woord
    onder welk shot ligt."""
    def nep(bron, cache, *, taal="auto", log=print):
        return [Woord(f"{bron.stem}-{i}", i + 0.1, i + 0.4) for i in range(60)]

    monkeypatch.setattr(transcript, "transcribeer_clip", nep)
    # Stap 4 legt de spraak alleen uit de cache opnieuw (review 15-10).
    monkeypatch.setattr(transcript, "heeft_cache", lambda *a, **k: True)


def _eerste_woord_per_shot(pdir):
    edl = EDL.lees(pdir / "edl.json")
    regels = json.loads((pdir / "ondertitels.json").read_text())["regels"]
    woorden = [w for r in regels for w in r["woorden"]]
    uit = []
    for b in sorted(edl.video, key=lambda b: b.tijdlijn_start):
        z = b.tijdlijn_start + b.duur
        hier = [w for w in woorden if b.tijdlijn_start <= w["start"] < z]
        uit.append((b.bestand.rsplit(".", 1)[0], hier[0]["tekst"].rsplit("-", 1)[0] if hier else None))
    return uit


@nodig_ffmpeg
def test_ondertitels_verhuizen_mee_met_een_verplaatst_shot(gemonteerd, monkeypatch):  # noqa: F811
    project, _ = gemonteerd
    pdir = paths.project_dir(project)
    _nep_transcript(monkeypatch)
    spraak._schrijf_instellingen(project, dict(spraak.STANDAARD, aan=True))
    edl = EDL.lees(pdir / "edl.json")
    spraak._leg_op(edl, pdir, spraak.instellingen(project), log=lambda *_: None)
    edl.schrijf(pdir / "edl.json")

    eerste = sorted(edl.video, key=lambda b: b.tijdlijn_start)[0].id
    monteren.verplaats(project, eerste, 2)
    # Elk shot heeft na het verplaatsen de woorden van zijn eigen clip.
    paren = _eerste_woord_per_shot(pdir)
    assert paren and all(clip == woord for clip, woord in paren if woord), paren

    # Ook een andere snelheid via zet_shot legt de spraak opnieuw.
    shot = EDL.lees(pdir / "edl.json").video[0]
    bijwerken.zet_shot(project, shot.id, snelheid=0.5)
    paren = _eerste_woord_per_shot(pdir)
    assert all(clip == woord for clip, woord in paren if woord), paren


@nodig_ffmpeg
def test_zet_shot_schrijft_niet_onder_lopend_werk_door(gemonteerd):  # noqa: F811
    project, _ = gemonteerd
    shot = EDL.lees(paths.project_dir(project) / "edl.json").video[0].id
    assert projecten.neem_bezig(project, "Spraak herkennen…")
    try:
        with pytest.raises(RuntimeError, match="al werk"):
            bijwerken.zet_shot(project, shot, snelheid=0.5)
    finally:
        projecten.zet_bezig(project, None)


@nodig_ffmpeg
def test_een_andere_snelheid_stemt_de_kleur_opnieuw_af(gemonteerd, monkeypatch):  # noqa: F811
    project, _ = gemonteerd
    from cve import kleurmatch

    aanroepen = []
    echt = kleurmatch.stem_af
    monkeypatch.setattr(kleurmatch, "stem_af", lambda *a, **k: (aanroepen.append(1), echt(*a, **k))[1])
    shot = EDL.lees(paths.project_dir(project) / "edl.json").video[0]
    bijwerken.zet_shot(project, shot.id, snelheid=0.5 if shot.snelheid != 0.5 else 1.0)
    assert aanroepen
    # Alleen stabiliseren verandert de bron niet: geen nieuwe afstemming.
    aanroepen.clear()
    bijwerken.zet_shot(project, shot.id, stabiliseer=True)
    assert not aanroepen



def test_het_geleerde_staat_in_de_app_niet_in_de_bundel(monkeypatch, tmp_path):
    """Ingevroren wees `styles/` in de app-bundel; daar schrijven breekt de
    handtekening en een update gooit het weg."""
    import sys

    from cve import geheugen

    monkeypatch.delenv("CVE_GELEERD", raising=False)
    monkeypatch.setenv("BEATCUT_STEUN", str(tmp_path / "steun"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert geheugen.geleerd_map() == (tmp_path / "steun" / "geleerd").resolve()
    monkeypatch.setenv("CVE_GELEERD", str(tmp_path / "eigen"))
    assert geheugen.geleerd_map() == tmp_path / "eigen"
    monkeypatch.delenv("CVE_GELEERD")
    monkeypatch.delattr(sys, "frozen")
    assert geheugen.geleerd_map() == paths.STYLES / "geleerd"


# -- review van 15-10-2026 ----------------------------------------------------


@nodig_ffmpeg
def test_stap4_start_nooit_whisper_in_de_rpc_lus(gemonteerd, monkeypatch):  # noqa: F811
    """Zonder transcript in de cache laat een trim de laag staan in plaats van
    tientallen seconden te gaan transcriberen."""
    project, _ = gemonteerd
    pdir = paths.project_dir(project)
    spraak._schrijf_instellingen(project, dict(spraak.STANDAARD, aan=True))

    def verboden(*a, **k):
        raise AssertionError("whisper gestart in de RPC-lus")

    monkeypatch.setattr(transcript, "transcribeer_clip", verboden)
    monkeypatch.setattr(transcript, "heeft_cache", lambda *a, **k: False)
    shot = EDL.lees(pdir / "edl.json").video[0].id
    monteren.trim(project, shot, "eind", 1)  # mag niet ontploffen


@nodig_ffmpeg
def test_ducking_volgt_edl_ook_na_ongedaan(gemonteerd, monkeypatch):  # noqa: F811
    """De muziek duikt op de tijden van de laag in edl.json, niet op die van
    ondertitels.json (dat bestand gaat niet mee met ongedaan maken)."""
    from cve import render

    project, _ = gemonteerd
    pdir = paths.project_dir(project)
    _nep_transcript(monkeypatch)
    # Dun gezaaid: één kort woord per 1,3 s bron, zodat de duikvensters los
    # van elkaar staan en een trim ze zichtbaar verschuift.
    monkeypatch.setattr(
        transcript, "transcribeer_clip",
        lambda bron, *a, **k: [Woord(f"w{i}", i * 1.3 + 0.1, i * 1.3 + 0.3) for i in range(40)],
    )
    spraak._schrijf_instellingen(project, dict(spraak.STANDAARD, aan=True))
    edl = EDL.lees(pdir / "edl.json")
    spraak._leg_op(edl, pdir, spraak.instellingen(project), log=lambda *_: None)
    monteren.schrijf_met_stap(pdir, edl)
    voor = render._duck_uitdrukking(EDL.lees(pdir / "edl.json"), pdir)

    eerste = sorted(EDL.lees(pdir / "edl.json").video, key=lambda b: b.tijdlijn_start)[0].id
    monteren.trim(project, eerste, "eind", 1)
    assert render._duck_uitdrukking(EDL.lees(pdir / "edl.json"), pdir) != voor
    monteren.ongedaan(project)
    # ondertitels.json staat nog op de getrimde tijden; de ducking niet.
    assert render._duck_uitdrukking(EDL.lees(pdir / "edl.json"), pdir) == voor
    assert spraak.stand(project)["regels"] > 0


def test_een_clip_zonder_geluid_krijgt_ook_een_cache(tmp_path, monkeypatch):
    """Codex 15-10: zonder cache voor een stille clip legde stap 4 de
    ondertitels nooit meer opnieuw zodra er één drone-clip in de montage stond."""
    monkeypatch.setattr(paths, "whisper_bin", lambda: tmp_path / "whisper-cli")
    monkeypatch.setattr(paths, "whisper_model", lambda: tmp_path / "model.bin")
    monkeypatch.setattr(transcript, "_wav", lambda bron, cache: None)
    bron = tmp_path / "drone.mp4"
    bron.write_bytes(b"x")
    assert transcript.transcribeer_clip(bron, tmp_path / "cache") == []
    assert transcript.heeft_cache(bron, tmp_path / "cache")
    assert transcript.transcribeer_clip(bron, tmp_path / "cache") == []  # nu uit de cache


def test_deshake_werkt_in_over_de_aanloop():
    """Codex 15-10: de overgangsstaart begon `deshake` opnieuw en versprong op
    de snede. Nu loopt hij vóór de `trim` en krijgt hij 4 s aanloop (gemeten:
    na 3 s is een losse staart identiek aan doorlopend stabiliseren)."""
    from cve import render
    from cve.edl import VideoBlok

    edl = EDL(project="p", video=[])
    blok = VideoBlok(id="v0", clip="C01", bestand="a.mp4", bron_start=10.0, duur=2.0,
                     tijdlijn_start=0.0, stabiliseer=True)
    keten = render._blokfilter(blok, edl, aanloop=4.0)
    assert keten.index("deshake") < keten.index("trim=start=4.000")
    assert render.STABIEL_AANLOOP >= 3.0
    zonder = render._blokfilter(VideoBlok(id="v1", clip="C01", bestand="a.mp4", bron_start=10.0,
                                          duur=2.0, tijdlijn_start=0.0), edl, aanloop=2.0)
    assert "deshake" not in zonder
