"""Muziek genereren: de hele keten met een nep-model, en één echte generatie.

Twee lagen, met opzet gescheiden:

1. **Zonder model** (`nepmuziekserver.py`) draait de hele RPC-keten: status,
   genereren met voortgang, nabewerking, de `.json` ernaast, en kiezen als
   projectmuziek. Dat loopt op elke machine en in CI.
2. **Mét het echte model** één generatie van 15 s house op 124 BPM, en dan
   meten wat eruit komt. Die test slaat zichzelf over als ACE-Step er niet
   staat — het model is 11 GB en hoort niet in git.

De interessante bewering van laag 1 is de trim: de nep-server zet er, net als
het echte model, 20 % stilte achter. Komt die eruit, dan werkt de stap die het
echte probleem van ACE-Step oplost (`vendor/ace-step/VERSLAG.md` §4).
"""

import json
import math
import time
from pathlib import Path

import pytest
from cve import montage, muziekgen, paths, rpc

from test_rpc_project import _vraag, losse_projectmap, nodig_ffmpeg, opgevangen  # noqa: F401

NEPSERVER = Path(__file__).with_name("nepmuziekserver.py")
DUUR = 20.0
BPM = 124


@pytest.fixture
def nepmodel(tmp_path, monkeypatch):
    """Een installatie die er compleet uitziet, met de nep-server erachter.

    `paths.muziekmodel()` eist een venv-Python en de modelgewichten voordat
    hij een map goedkeurt. Die eis wordt hier nagemaakt, zodat ook die controle
    in de test meeloopt in plaats van eromheen.
    """
    wortel = tmp_path / "muziekmodel"
    (wortel / "acestep").mkdir(parents=True)
    (wortel / "checkpoints" / "acestep-v15-turbo").mkdir(parents=True)
    venv = wortel / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").write_text("#!/bin/sh\n")
    monkeypatch.setenv("BEATCUT_MUZIEKMODEL", str(wortel))
    monkeypatch.setenv("BEATCUT_MUZIEKSERVER", str(NEPSERVER))
    # De server is een modulevariabele; zonder dit houdt een volgende test de
    # server van deze vast en wijst die naar een opgeruimde tijdelijke map.
    muziekgen.stop_server()
    yield wortel
    muziekgen.stop_server()


def _project(naam="muziektest"):
    _vraag("project.maak", naam=naam)
    return naam


def _wacht(regels, gebeurtenis, werk, seconden=180.0):
    tot = time.monotonic() + seconden
    while time.monotonic() < tot:
        for r in regels:
            d = r.get("data") or {}
            if r.get("gebeurtenis") == gebeurtenis and d.get("werk") == werk:
                return d
            if r.get("gebeurtenis") == "fout" and d.get("werk") == werk:
                pytest.fail(f"engine meldde een fout: {d.get('fout')}")
        time.sleep(0.2)
    pytest.fail(f"geen {gebeurtenis}/{werk} binnen {seconden} s; wel: {regels}")


def test_status_zonder_model_vertelt_dat_het_ontbreekt(monkeypatch):
    monkeypatch.setattr(paths, "muziekmodel", lambda: None)
    s = _vraag("muziek.status")
    assert s["aanwezig"] is False
    assert s["pad"] is None
    assert "11 GB" in s["uitleg"]
    # De genres komen ook zonder model mee: de interface moet de chips kunnen
    # tonen naast de kaart "nog niet geïnstalleerd".
    assert [g["naam"] for g in s["genres"]][:2] == ["Pop", "House"]


def test_status_met_model_noemt_pad_en_grootte(nepmodel):
    s = _vraag("muziek.status")
    assert s["aanwezig"] is True
    assert s["pad"] == str(nepmodel)
    assert s["bytes"] > 0
    assert "ACE-Step 1.5 (MIT)" in s["licentie"]


def test_bpm_voorstel_volgt_de_stijl():
    # Actie wil snel, luchtvaart wil ruimte - en het genre trekt het bij.
    assert muziekgen.bpm_voorstel("actie", "House") > muziekgen.bpm_voorstel("luchtvaart", "House")
    assert muziekgen.bpm_voorstel("reis", None) == muziekgen.BPM_PER_STIJL["reis"]
    assert muziekgen.bpm_voorstel("bestaat-niet", None) == muziekgen.BPM_STANDAARD


@nodig_ffmpeg
def test_genereren_trimt_de_stille_staart_en_sluit_op_een_maat(
    nepmodel, losse_projectmap, opgevangen  # noqa: F811
):
    project = _project()
    antwoord = _vraag(
        "muziek.genereer", project=project, genre="House", bpm=BPM,
        duur=DUUR, zang=False, varianten=2,
    )
    assert antwoord == {"gestart": True, "bezig": False}

    data = _wacht(opgevangen, "klaar", "muziekgen")
    varianten = data["varianten"]
    assert len(varianten) == 2
    assert [v["variant"] for v in varianten] == ["A", "B"]
    assert len({v["seed"] for v in varianten}) == 2, "varianten moeten verschillende seeds hebben"

    maat = 4 * 60.0 / BPM
    for v in varianten:
        pad = Path(v["pad"])
        assert pad.is_file()
        assert pad.parent == paths.PROJECTEN / project / "muziek" / "gegenereerd"

        # De nep-server zet 20 % stilte achter een track van 20 s: 4 s eraf.
        assert v["stilte_weg"] == pytest.approx(DUUR * 0.2, abs=0.2)
        # Wat overblijft is een heel aantal maten van 124 BPM.
        assert v["maten"] >= 1
        assert v["duur"] == pytest.approx(v["maten"] * maat, abs=0.05)
        assert v["duur"] < DUUR

        # En de staart van het resultaat is stil gemaakt door de fade, niet
        # leeg gelaten: de laatste stilte mag niet terug zijn.
        lengte, einde = muziekgen.muziekeinde(pad)
        assert lengte == pytest.approx(v["duur"], abs=0.1)
        assert lengte - einde < 0.6, "er zit opnieuw een stille staart in"

        # De json ernaast moet de licentie dragen: anders weet niemand later
        # nog waarom dit nummer vrij te gebruiken is.
        naast = json.loads(pad.with_suffix(".json").read_text(encoding="utf-8"))
        assert naast["licentie"] == muziekgen.LICENTIE
        assert naast["bpm"] == BPM
        assert naast["genre"] == "House"
        assert naast["prompt"] and "124 BPM" in naast["prompt"]
        assert naast["seed"] == v["seed"]

    # Voortgang per variant, zodat de balk in de app iets te doen heeft.
    stappen = [
        r["data"] for r in opgevangen
        if r.get("gebeurtenis") == "voortgang" and r["data"].get("werk") == "muziekgen"
    ]
    assert any("Variant A" in s["tekst"] for s in stappen)
    assert any("Variant B" in s["tekst"] for s in stappen)
    assert stappen[-1]["percentage"] == 100

    # En `muziek.status` met project erbij vindt ze terug na een herstart.
    s = _vraag("muziek.status", project=project)
    assert len(s["varianten"]) == 2


@nodig_ffmpeg
def test_kiezen_zet_de_variant_als_projectmuziek(
    nepmodel, losse_projectmap, opgevangen  # noqa: F811
):
    project = _project("kiestest")
    _vraag("muziek.genereer", project=project, genre="Lofi", bpm=BPM, duur=DUUR, varianten=1)
    variant = _wacht(opgevangen, "klaar", "muziekgen")["varianten"][0]

    antwoord = _vraag("muziek.kies", project=project, pad=variant["pad"])
    assert antwoord["bestand"] == variant["bestand"]

    # Dezelfde route als "Kies muziek…": een kopie in muziek/, bron onaangeroerd.
    assert Path(variant["pad"]).is_file()
    assert (paths.PROJECTEN / project / "muziek" / variant["bestand"]).is_file()
    assert montage._huidige_muziek(project).name == variant["bestand"]

    # De BPM-meting loopt daarna in een werkdraad, net als bij "Kies muziek…".
    # Hij belandt niet in `analysis.json` zolang die niet bestaat - dit project
    # heeft nooit een analyse gedraaid - maar de app krijgt hem wel.
    gemeten = _wacht(opgevangen, "klaar", "muziek", seconden=120.0)["muziek"]
    assert gemeten["bestand"] == variant["bestand"]
    assert gemeten["duur"] == pytest.approx(variant["duur"], abs=0.2)


def test_kiezen_zonder_pad_is_een_nette_fout(nepmodel, losse_projectmap):  # noqa: F811
    with pytest.raises(ValueError, match="'pad' ontbreekt"):
        rpc.METHODES["muziek.kies"]({"project": _project("leeg")})


def test_genereren_zonder_model_zegt_waar_het_vandaan_moet_komen(
    monkeypatch, losse_projectmap, opgevangen  # noqa: F811
):
    monkeypatch.setattr(paths, "muziekmodel", lambda: None)
    muziekgen.stop_server()
    project = _project("geenmodel")
    _vraag("muziek.genereer", project=project)
    fout = next(
        r["data"] for r in _foutjes(opgevangen) if r["data"].get("werk") == "muziekgen"
    )
    assert "niet geïnstalleerd" in fout["fout"]


def _foutjes(regels, seconden=20.0):
    tot = time.monotonic() + seconden
    while time.monotonic() < tot:
        hits = [r for r in regels if r.get("gebeurtenis") == "fout"]
        if hits:
            return hits
        time.sleep(0.1)
    pytest.fail(f"geen foutmelding; wel: {regels}")


# -- met het echte model ---------------------------------------------------

echt_model = pytest.mark.skipif(
    paths.muziekmodel() is None,
    reason="ACE-Step 1.5 staat niet op deze machine (11 GB, niet in git)",
)


@echt_model
@nodig_ffmpeg
def test_echte_generatie_house_124(losse_projectmap, opgevangen):  # noqa: F811
    """Eén echte track, en dan meten wat er uit komt.

    **Deze test toetst niet dat ACE-Step het gevraagde tempo haalt.** Dat doet
    hij niet betrouwbaar: drie runs met dezelfde opdracht gaven 129,2 — 124,0 —
    99,4 BPM, en met `int(time.time())` als seed was de uitslag dus een
    dobbelsteen die `release.sh` kon laten vallen.

    Wat we wél beloven, en wat hier dus in staat: de seed ligt vast (dus de run
    is herhaalbaar), het gemeten tempo wordt eerlijk gerapporteerd, de montage
    blijft op de tel (de track eindigt op een hele maat van het gevraagde
    tempo), de loudness staat op de aanlevernorm (-14 LUFS ±1), de true peak
    onder -1 dBTP, en er zit geen seconde stilte aan het eind.
    """
    from cve import media, render

    muziekgen.stop_server()
    project = _project("echtemuziek")
    _vraag(
        "muziek.genereer", project=project, genre="House", bpm=BPM,
        duur=15.0, varianten=1, seed=20261003,
    )
    variant = _wacht(opgevangen, "klaar", "muziekgen", seconden=900.0)["varianten"][0]
    pad = Path(variant["pad"])

    # 1. De montage blijft op de tel: de track is afgeknipt op een heel aantal
    #    maten van het gevráágde tempo, want dáárop snijdt de regisseur.
    maat = 4 * 60.0 / BPM
    assert variant["duur"] == pytest.approx(variant["maten"] * maat, abs=0.05)
    assert 0 < variant["duur"] <= 15.0

    # 2. Het gemeten tempo wordt correct gerapporteerd. Niet "het klopt", maar
    #    "wat er staat is wat er te meten valt" — daar kijkt de gebruiker naar.
    assert variant["bpm_gemeten"] == muziekgen._gemeten_bpm(pad)
    assert variant["bpm_afwijking"] == muziekgen.bpm_afwijking(variant["bpm_gemeten"], BPM)
    # 3. De seed ligt vast: deze run is herhaalbaar. Welke van de drie
    #    pogingen hij werd hangt van het model af, maar hij komt uit onze reeks.
    assert variant["seed"] in {20261003 + p * 104729 for p in range(muziekgen.BPM_POGINGEN)}
    assert variant["bpm_afwijking"] is not None, "librosa vond geen tempo in een housetrack"

    # 4 en 5. Loudness en true peak, gemeten met dezelfde loudnorm-meetronde
    #         die de renderer gebruikt.
    meting = render._loudnorm_meting(
        ["-i", str(pad)], ["[0:a]anull[a]"], "[a]",
        f"I={media.LUFS_DOEL}:TP={media.TRUE_PEAK_DOEL}:LRA={media.LRA_DOEL}",
    )
    assert meting is not None, "loudnorm kon het bestand niet meten"
    assert float(meting["input_i"]) == pytest.approx(media.LUFS_DOEL, abs=1.0)
    assert float(meting["input_tp"]) <= media.TRUE_PEAK_DOEL + 0.05

    # 6. Geen stille staart meer.
    lengte, einde = muziekgen.muziekeinde(pad)
    assert lengte - einde < 1.0, f"nog {lengte - einde:.2f} s stilte aan het eind"
    assert math.isclose(lengte, variant["duur"], abs_tol=0.1)


# --------------------------------------------------------------------------
# Een model dat stilvalt
# --------------------------------------------------------------------------

STIL = (
    'import sys\n'
    'print(\'{"gereed": true, "model": "stil"}\', flush=True)\n'
    'for regel in sys.stdin:\n'
    '    if "stop" in regel:\n'
    '        break\n'
    '# Verder komt er niets: dit is een model dat blijft hangen.\n'
)
ZWIJGT_METEEN = 'import sys\nfor regel in sys.stdin:\n    pass\n'


def test_stilgevallen_model_geeft_een_nette_fout_en_laat_het_slot_los(tmp_path, monkeypatch):
    """`readline()` is niet af te breken.

    Een model dat na de handshake zwijgt hield de werkdraad én het serverslot
    voor altijd bezet, ook al stond er een deadline bij — gemeten met een
    zwijgend subprocess dat na 0,2 s nog hing bij een deadline van 0,05 s.
    """
    script = tmp_path / "stil.py"
    script.write_text(STIL, encoding="utf-8")
    monkeypatch.setenv("BEATCUT_MUZIEKSERVER", str(script))
    monkeypatch.setattr(muziekgen, "GEDULD_TRACK", 0.5)

    srv = muziekgen.Server(tmp_path)
    try:
        begin = time.monotonic()
        with pytest.raises(TimeoutError):
            srv.vraag({"caption": "iets"})
        assert time.monotonic() - begin < 20, "de deadline ging niet af"
        assert srv._slot.acquire(blocking=False), "het slot is niet vrijgekomen"
        srv._slot.release()
    finally:
        srv.stop()


def test_model_dat_niet_opstart_loopt_op_zijn_deadline_af(tmp_path, monkeypatch):
    """Ook de handshake moet aflopen; anders hangt de hele app bij 'laden…'."""
    script = tmp_path / "zwijgt.py"
    script.write_text(ZWIJGT_METEEN, encoding="utf-8")
    monkeypatch.setenv("BEATCUT_MUZIEKSERVER", str(script))
    monkeypatch.setattr(muziekgen, "GEDULD_START", 0.5)

    srv = muziekgen.Server(tmp_path)
    with pytest.raises(TimeoutError):
        srv.start()
    # `start()` ruimt zijn eigen proces op, anders leest de volgende vraag het
    # late `gereed` als trackantwoord.
    assert srv._proc is None
