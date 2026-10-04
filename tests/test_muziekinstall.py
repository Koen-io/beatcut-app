"""Het muziekmodel installeren vanuit de app — zonder 11 GB en zonder internet.

Wat hier getoetst wordt is niet de download zelf maar de dingen die stil
misgaan: hervatten, annuleren, te weinig schijfruimte, en een archief dat
onderweg veranderd is. De echte bestanden worden nagemaakt door een
HTTP-servertje op localhost, zodat `urllib` precies hetzelfde pad loopt als bij
GitHub.

Eén test raakt wél het netwerk: `test_de_echte_adressen_bestaan` doet een
HEAD-verzoek op de uv-release en de broncode-zip. Die slaat zichzelf over
tenzij `BEATCUT_NETTEST=1` staat — anders faalt de release-poort zodra de
internetverbinding even wegvalt.
"""

import hashlib
import io
import json
import os
import sys
import tarfile
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cve import muziekinstall, paths, rpc


# -- gereedschap -----------------------------------------------------------


@pytest.fixture
def webserver(tmp_path):
    """Een map op localhost aanbieden. Geeft (map, adres) terug."""
    wortel = tmp_path / "web"
    wortel.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(wortel))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield wortel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def steunmap(tmp_path, monkeypatch):
    """De steunmap naar een tijdelijke map, en geen model in zicht.

    `paths.muziekmodel()` kijkt ook in `vendor/ace-step`, en op de machine van
    Koen staat die echt. Zonder dit zou `installeer()` meteen "al aanwezig"
    melden en de test niets toetsen.
    """
    d = tmp_path / "steun"
    d.mkdir()
    monkeypatch.setattr(paths, "steun_map", lambda: d)
    monkeypatch.setattr(paths, "muziekmodel", lambda: None)
    return d


def _nep_uv_archief(doel: Path) -> str:
    """Een tar.gz die eruitziet als een uv-release. Geeft de sha256 terug."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for naam in ("uv", "uvx"):
            inhoud = f"#!/bin/sh\necho nep-{naam}\n".encode()
            # Windows-releases heten uv.exe; uv_pad() zoekt daar ook naar.
            exe = f"{naam}.exe" if sys.platform.startswith("win") else naam
            info = tarfile.TarInfo(f"uv-nep-platform/{exe}")
            info.size = len(inhoud)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(inhoud))
    ruw = buf.getvalue()
    doel.write_bytes(ruw)
    return hashlib.sha256(ruw).hexdigest()


def _nep_broncode_zip(doel: Path) -> None:
    """Een zip zoals GitHub hem levert: één map met alles erin."""
    with zipfile.ZipFile(doel, "w") as z:
        z.writestr("ACE-Step-1.5-abc123/pyproject.toml", "[project]\nname='nep'\n")
        z.writestr("ACE-Step-1.5-abc123/acestep/__init__.py", "")
        z.writestr("ACE-Step-1.5-abc123/acestep/model_downloader.py", "")


def _zet_uv_klaar(web: Path, adres: str, monkeypatch) -> str:
    """Het nep-archief aanbieden en de module ernaar laten wijzen."""
    naam = "uv-nep.tar.gz"
    sha = _nep_uv_archief(web / naam)
    monkeypatch.setattr(muziekinstall, "UV_BASIS", adres)
    monkeypatch.setattr(muziekinstall, "UV_UITGAVEN", {muziekinstall._sleutel(): (naam, sha)})
    return sha


# -- downloaden ------------------------------------------------------------


def test_download_met_het_juiste_controlegetal_komt_aan(tmp_path, webserver):
    web, adres = webserver
    sha = _nep_uv_archief(web / "ding.tar.gz")
    doel = tmp_path / "ding.tar.gz"

    gezien: list[tuple] = []
    muziekinstall._download(f"{adres}/ding.tar.gz", doel, melder=lambda *a: gezien.append(a),
                            stap="uv", tekst="Ophalen…", sha256=sha)

    assert doel.exists()
    assert hashlib.sha256(doel.read_bytes()).hexdigest() == sha
    assert gezien and gezien[0][0] == "uv"
    # Niets blijft als `.deel` achter als het goed ging.
    assert not (tmp_path / "ding.tar.gz.deel").exists()


def test_download_met_een_fout_controlegetal_wordt_geweigerd(tmp_path, webserver):
    web, adres = webserver
    _nep_uv_archief(web / "ding.tar.gz")
    doel = tmp_path / "ding.tar.gz"

    with pytest.raises(RuntimeError, match="controlegetal"):
        muziekinstall._download(f"{adres}/ding.tar.gz", doel, melder=None, stap="uv",
                                tekst="Ophalen…", sha256="00" * 32)

    # En er blijft niets liggen dat voor goed kan doorgaan.
    assert not doel.exists()
    assert not (tmp_path / "ding.tar.gz.deel").exists()


def test_annuleren_stopt_de_download(tmp_path, webserver):
    web, adres = webserver
    _nep_uv_archief(web / "ding.tar.gz")
    stop = threading.Event()
    stop.set()

    with pytest.raises(muziekinstall.Gestopt):
        muziekinstall._download(f"{adres}/ding.tar.gz", tmp_path / "ding.tar.gz",
                                melder=None, stap="uv", tekst="Ophalen…", stop=stop)


# -- de stappen ------------------------------------------------------------


def test_uv_komt_in_de_steunmap_en_wordt_niet_tweemaal_gehaald(
    steunmap, webserver, monkeypatch
):
    web, adres = webserver
    _zet_uv_klaar(web, adres, monkeypatch)

    uv = muziekinstall._stap_uv(melder=None, stop=None)
    assert uv == muziekinstall.uv_pad()
    assert uv.parent == steunmap / "bin"
    assert os.access(uv, os.X_OK)

    # Hervatten: het adres is nu kapot. Staat uv er al, dan hoort dat niet uit
    # te maken — dat is de hele belofte van "wat er staat blijft staan".
    monkeypatch.setattr(muziekinstall, "UV_BASIS", "http://127.0.0.1:1/bestaat-niet")
    assert muziekinstall._stap_uv(melder=None, stop=None) == uv


def test_broncode_wordt_uitgepakt_en_daarna_overgeslagen(steunmap, webserver, monkeypatch):
    web, adres = webserver
    _nep_broncode_zip(web / "code.zip")
    monkeypatch.setattr(muziekinstall, "ACESTEP_ZIP", f"{adres}/code.zip")

    doel = muziekinstall._stap_code(melder=None, stop=None)
    assert doel == muziekinstall.doelmap()
    assert (doel / "acestep" / "model_downloader.py").exists()
    assert (doel / "pyproject.toml").exists()
    # De tijdelijke map is opgeruimd zodra het gelukt is.
    assert not muziekinstall.deelmap().exists()

    monkeypatch.setattr(muziekinstall, "ACESTEP_ZIP", "http://127.0.0.1:1/bestaat-niet")
    assert muziekinstall._stap_code(melder=None, stop=None) == doel


def test_een_halve_poging_hergebruikt_de_zip_die_er_al_ligt(steunmap, monkeypatch):
    """Na annuleren ligt de zip in `.deel`. Dan hoeft hij niet opnieuw."""
    deel = muziekinstall.deelmap()
    deel.mkdir(parents=True)
    _nep_broncode_zip(deel / "broncode.zip")
    monkeypatch.setattr(muziekinstall, "ACESTEP_ZIP", "http://127.0.0.1:1/bestaat-niet")

    doel = muziekinstall._stap_code(melder=None, stop=None)
    assert (doel / "acestep" / "__init__.py").exists()


def test_een_halve_doelmap_blijft_staan_en_wordt_aangevuld(steunmap, monkeypatch):
    """Een venv of al opgehaalde gewichten mogen nooit sneuvelen."""
    deel = muziekinstall.deelmap()
    deel.mkdir(parents=True)
    _nep_broncode_zip(deel / "broncode.zip")
    doel = muziekinstall.doelmap()
    (doel / "checkpoints" / "acestep-v15-turbo").mkdir(parents=True)
    (doel / "checkpoints" / "acestep-v15-turbo" / "halve-download.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(muziekinstall, "ACESTEP_ZIP", "http://127.0.0.1:1/bestaat-niet")

    muziekinstall._stap_code(melder=None, stop=None)
    assert (doel / "acestep" / "__init__.py").exists()
    assert (doel / "checkpoints" / "acestep-v15-turbo" / "halve-download.bin").exists()


# -- schijfruimte ----------------------------------------------------------


def test_te_weinig_ruimte_geeft_een_nette_fout_voordat_er_iets_gebeurt(
    steunmap, monkeypatch
):
    monkeypatch.setattr(muziekinstall, "ruimte_vrij", lambda: 3_000_000_000)
    with pytest.raises(RuntimeError, match="3.0 GB vrij"):
        muziekinstall.installeer()
    # Niets aangeraakt: geen uv, geen halve map.
    assert muziekinstall.uv_pad() is None
    assert not muziekinstall.doelmap().exists()


def test_ruimte_vrij_meet_de_echte_schijf(steunmap):
    assert muziekinstall.ruimte_vrij() > 0


def test_een_al_aanwezig_model_wordt_niet_opnieuw_gehaald(steunmap, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "muziekmodel", lambda: tmp_path / "ergens")
    uit = muziekinstall.installeer()
    assert uit["al_aanwezig"] is True


# -- de achtergronddraad en de RPC ----------------------------------------


@pytest.fixture
def opgevangen(monkeypatch):
    regels: list[dict] = []
    monkeypatch.setattr(rpc, "_schrijf", regels.append)
    return regels


def _vraag(methode: str, **params):
    antwoord = rpc.verwerk(json.dumps({"id": 1, "methode": methode, "params": params}))
    assert "fout" not in antwoord, antwoord
    return antwoord["resultaat"]


def _wacht_op(regels, gebeurtenis, seconden=10.0):
    tot = time.monotonic() + seconden
    while time.monotonic() < tot:
        for r in regels:
            if r.get("gebeurtenis") == gebeurtenis and \
                    (r.get("data") or {}).get("werk") == "muziekinstall":
                return r["data"]
        time.sleep(0.05)
    pytest.fail(f"geen {gebeurtenis}/muziekinstall binnen {seconden} s; wel: {regels}")


def test_een_tegelijk_en_annuleren_meldt_zich(steunmap, monkeypatch, opgevangen):
    """De draad, de "één tegelijk"-regel en Annuleren, zonder echte download."""
    begonnen = threading.Event()

    def nep_installeer(melder=None, stop_event=None):
        if melder:
            melder("gewichten", 1_000_000, 9_400_000_000, "Modelgewichten ophalen…")
        begonnen.set()
        stop_event.wait(10.0)
        raise muziekinstall.Gestopt("gestopt")

    monkeypatch.setattr(muziekinstall, "installeer", nep_installeer)

    assert _vraag("muziek.installeer") == {"gestart": True}
    assert begonnen.wait(5.0)
    # Tweede keer: niets gestart, want er loopt er al een.
    assert _vraag("muziek.installeer") == {"gestart": False}
    assert _vraag("muziek.status")["installeren_bezig"] is True
    assert any(w["tekst"] == "Muziekmodel installeren…" for w in _vraag("bezig")["werk"])

    voortgang = _wacht_op(opgevangen, "voortgang")
    assert voortgang["stap"] == "gewichten"
    assert voortgang["totaal"] == 9_400_000_000
    # 28 % voor de stap begint, en één promille van 9,4 GB schuift nauwelijks op.
    assert voortgang["percentage"] == 28

    assert _vraag("muziek.installeer_stop") == {"gestopt": True}
    fout = _wacht_op(opgevangen, "fout")
    assert fout["soort"] == "Gestopt"
    assert "blijft staan" in fout["fout"]
    tot = time.monotonic() + 5.0
    while muziekinstall.is_bezig() and time.monotonic() < tot:
        time.sleep(0.05)
    assert muziekinstall.is_bezig() is False
    assert _vraag("muziek.installeer_stop") == {"gestopt": False}


def test_klaar_meldt_het_pad(steunmap, monkeypatch, opgevangen):
    monkeypatch.setattr(muziekinstall, "installeer",
                        lambda melder=None, stop_event=None: {"al_aanwezig": False,
                                                              "pad": "/ergens", "bytes": 7})
    assert _vraag("muziek.installeer") == {"gestart": True}
    klaar = _wacht_op(opgevangen, "klaar")
    assert klaar["pad"] == "/ergens"
    assert klaar["bytes"] == 7


def test_status_zonder_model_meldt_dat_er_niets_loopt(monkeypatch):
    monkeypatch.setattr(paths, "muziekmodel", lambda: None)
    s = _vraag("muziek.status")
    assert s["aanwezig"] is False
    assert s["installeren_bezig"] is False


# -- de enige test die het internet nodig heeft ---------------------------


@pytest.mark.skipif(os.environ.get("BEATCUT_NETTEST") != "1",
                    reason="raakt het internet; zet BEATCUT_NETTEST=1")
def test_de_echte_adressen_bestaan():
    """Bestaan de gepinde uv-release en de broncode-zip nog? Alleen een HEAD."""
    import urllib.request

    naam, _ = muziekinstall.UV_UITGAVEN[muziekinstall._sleutel()]
    for url in (f"{muziekinstall.UV_BASIS}/{naam}", muziekinstall.ACESTEP_ZIP):
        verzoek = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(verzoek, timeout=60) as r:
            assert r.status == 200, url


# -- de gewichten-stap -----------------------------------------------------
#
# `installer/muziekmodel/installeer-mac.sh` riep `ensure_model` aan en dat
# bestaat niet in deze commit — een ImportError, gevonden op 03-10-2026 door de
# stap echt te draaien. En de echte functies geven `(gelukt, bericht)` terug in
# plaats van een uitzondering, dus een mislukte download zou als "klaar"
# doorgaan. Beide gevallen staan hieronder, met een namaak-downloader zodat er
# geen 9,4 GB aan te pas komt.


def _nep_downloader(doel: Path, gelukt: bool) -> None:
    pak = doel / "acestep"
    pak.mkdir(parents=True, exist_ok=True)
    (pak / "__init__.py").write_text("")
    (pak / "model_downloader.py").write_text(
        "def ensure_main_model(checkpoints_dir=None, token=None, prefer_source=None):\n"
        f"    return ({gelukt!r}, 'hoofdmodel')\n"
        "def ensure_lm_model(model_name=None, checkpoints_dir=None, token=None,\n"
        "                    prefer_source=None):\n"
        f"    return ({gelukt!r}, 'taalmodel')\n",
        encoding="utf-8",
    )


def test_gewichten_halen_gebruikt_de_namen_die_echt_bestaan(steunmap, tmp_path):
    """Het script moet werken tegen de API van de gepinde commit."""
    doel = tmp_path / "ace"
    _nep_downloader(doel, gelukt=True)
    muziekinstall._stap_gewichten(Path(sys.executable), doel, melder=None, stop=None)


def test_een_mislukte_download_gaat_niet_voor_klaar_door(steunmap, tmp_path):
    doel = tmp_path / "ace"
    _nep_downloader(doel, gelukt=False)
    with pytest.raises(RuntimeError, match="hoofdmodel"):
        muziekinstall._stap_gewichten(Path(sys.executable), doel, melder=None, stop=None)


def test_halve_installatie_in_de_steunmap_telt_niet(tmp_path, monkeypatch):
    """Codex-review 03-10 #12: modelmap aanwezig, marker niet -> niet compleet."""
    from cve import paths as p

    monkeypatch.setattr(p, "steun_map", lambda: tmp_path)
    monkeypatch.setattr(p, "VENDOR", tmp_path / "geen-vendor")
    monkeypatch.delenv("BEATCUT_MUZIEKMODEL", raising=False)
    d = tmp_path / "muziekmodel"
    (d / "acestep").mkdir(parents=True)
    (d / "checkpoints" / "acestep-v15-turbo").mkdir(parents=True)
    (d / ".venv" / "bin").mkdir(parents=True)
    (d / ".venv" / "bin" / "python3").write_text("")
    (d / ".venv" / "Scripts").mkdir(parents=True)
    (d / ".venv" / "Scripts" / "python.exe").write_text("")
    assert p.muziekmodel() is None
    (d / p.MUZIEKMODEL_GEREED).write_text("ok")
    assert p.muziekmodel() == d
