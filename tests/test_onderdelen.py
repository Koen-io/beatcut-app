"""De titels in de export klaarzetten — zonder internet en zonder 400 MB.

Wat hier getoetst wordt is niet de download zelf maar de dingen die stil
misgaan: hervatten, annuleren, een archief dat onderweg veranderd is, en de
vraag of de export ook echt *meldt* dat er geen titels in komen. De echte
bestanden worden nagemaakt door een HTTP-servertje op localhost, zodat
`urllib` precies hetzelfde pad loopt als bij nodejs.org.

Eén test raakt wél het netwerk: `test_de_echte_adressen_bestaan`. Die slaat
zichzelf over tenzij `BEATCUT_NETTEST=1` staat — anders faalt de release-poort
zodra de internetverbinding even wegvalt.
"""

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cve import graphics, onderdelen, paths, rpc

NEP_VERSIE = "v24.21.0"


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
    """Een tijdelijke steunmap, en een machine waarop níets staat.

    Op Koens Mac staat een node in `/usr/local/bin` en soms een
    `node_modules/` naast de repo. Zonder dit zou `_stap_node()` meteen
    "staat er al" melden en toetst de test niets.
    """
    d = tmp_path / "steun"
    d.mkdir()
    monkeypatch.setenv("BEATCUT_STEUN", str(d))
    monkeypatch.delenv("BEATCUT_CHROME", raising=False)
    monkeypatch.setattr(paths, "ROOT", tmp_path / "geen-wortel")
    monkeypatch.setattr(paths, "which", lambda naam: None)
    monkeypatch.setattr(paths, "node_bin", _alleen_eigen_node)
    return d


def _alleen_eigen_node() -> Path | None:
    """`paths.node_bin()` zonder de node van het systeem."""
    exe = "node.exe" if sys.platform.startswith("win") else "node"
    eigen = paths.steun_map() / "node"
    for p in (eigen / exe, eigen / "bin" / exe):
        if p.exists():
            return p
    return None


def _eigen_node_pad(steunmap: Path) -> Path:
    """Waar de opgehaalde node staat: op Windows in de hoofdmap, elders in bin/."""
    if sys.platform.startswith("win"):
        return steunmap / "node" / "node.exe"
    return steunmap / "node" / "bin" / "node"


def _nep_node_archief(doel: Path, *, met_npm: bool = False) -> str:
    """Een tar.gz die eruitziet als een node-release. Geeft de sha256 terug."""
    buf = io.BytesIO()
    binnen = f"node-{NEP_VERSIE}-nepplatform"
    # Zoals de echte releases: op Windows staan node.exe en npm.cmd in de
    # hoofdmap, elders in bin/.
    if sys.platform.startswith("win"):
        namen = ["node.exe"] + (["npm.cmd"] if met_npm else [])
    else:
        namen = ["bin/node"] + (["bin/npm"] if met_npm else [])
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for naam in namen:
            inhoud = f"#!/bin/sh\necho {NEP_VERSIE}\n".encode()
            info = tarfile.TarInfo(f"{binnen}/{naam}")
            info.size = len(inhoud)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(inhoud))
    ruw = buf.getvalue()
    doel.parent.mkdir(parents=True, exist_ok=True)
    doel.write_bytes(ruw)
    return hashlib.sha256(ruw).hexdigest()


def _zet_node_klaar(web: Path, adres: str, monkeypatch, *, met_npm: bool = False) -> str:
    naam = f"node-{NEP_VERSIE}-nepplatform.tar.gz"
    sha = _nep_node_archief(web / naam, met_npm=met_npm)
    monkeypatch.setattr(onderdelen, "NODE_BASIS", adres)
    monkeypatch.setattr(onderdelen, "NODE_UITGAVEN", {onderdelen._sleutel(): (naam, sha)})
    return sha


# -- status ----------------------------------------------------------------


def test_status_op_een_schone_machine_meldt_alle_drie_als_ontbrekend(steunmap):
    s = onderdelen.status()
    assert s["alles_klaar"] is False
    assert s["ontbreekt"] == ["node", "hyperframes", "chrome"]
    assert [o["naam"] for o in s["onderdelen"]] == ["node", "hyperframes", "chrome"]
    assert all(o["pad"] is None for o in s["onderdelen"])
    assert s["bezig"] is False
    # De uitleg is wat de gebruiker leest; vaktaal hoort daar niet in.
    assert "400 MB" in s["uitleg"]


def test_status_telt_een_node_die_er_staat_mee(steunmap, webserver, monkeypatch):
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)
    onderdelen._stap_node(melder=None, stop=None)

    s = onderdelen.status()
    assert s["ontbreekt"] == ["hyperframes", "chrome"]
    node = next(o for o in s["onderdelen"] if o["naam"] == "node")
    assert node["aanwezig"] is True
    assert node["pad"] == str(_eigen_node_pad(steunmap))


# -- node ophalen ----------------------------------------------------------


def test_node_komt_in_de_steunmap_met_een_gereed_marker(steunmap, webserver, monkeypatch):
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)

    gezien: list[tuple] = []
    exe = onderdelen._stap_node(melder=lambda *a: gezien.append(a), stop=None)

    assert exe == _eigen_node_pad(steunmap)
    assert os.access(exe, os.X_OK)
    assert onderdelen._marker("node").read_text(encoding="utf-8").strip() == NEP_VERSIE
    assert gezien and gezien[0][0] == "node"
    # De tijdelijke map is opgeruimd zodra het gelukt is.
    assert not onderdelen.deelmap().exists()


def test_node_wordt_niet_tweemaal_gehaald(steunmap, webserver, monkeypatch):
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)
    exe = onderdelen._stap_node(melder=None, stop=None)

    # Hervatten: het adres is nu kapot. Staat node er al, dan hoort dat niet
    # uit te maken — dat is de hele belofte van "wat er staat blijft staan".
    monkeypatch.setattr(onderdelen, "NODE_BASIS", "http://127.0.0.1:1/bestaat-niet")
    assert onderdelen._stap_node(melder=None, stop=None) == exe


def test_node_met_een_fout_controlegetal_wordt_geweigerd(steunmap, webserver, monkeypatch):
    web, adres = webserver
    naam = f"node-{NEP_VERSIE}-nepplatform.tar.gz"
    _nep_node_archief(web / naam)
    monkeypatch.setattr(onderdelen, "NODE_BASIS", adres)
    monkeypatch.setattr(onderdelen, "NODE_UITGAVEN", {onderdelen._sleutel(): (naam, "00" * 32)})

    with pytest.raises(RuntimeError, match="controlegetal"):
        onderdelen._stap_node(melder=None, stop=None)

    # En er blijft niets liggen dat voor goed kan doorgaan.
    assert not (onderdelen.deelmap() / naam).exists()
    assert not (onderdelen.deelmap() / f"{naam}.deel").exists()
    assert not onderdelen._marker("node").exists()
    assert paths.node_bin() is None


def test_een_archief_van_een_andere_versie_wordt_opnieuw_gehaald(
    steunmap, webserver, monkeypatch
):
    """Een halve poging mag hervatten, een verkeerd archief nooit hergebruiken."""
    web, adres = webserver
    sha = _zet_node_klaar(web, adres, monkeypatch)
    naam = f"node-{NEP_VERSIE}-nepplatform.tar.gz"
    # Precies de naam die hij zoekt, maar met andere inhoud: dat is het geval
    # dat eeuwig blijft hangen als je alleen op bestaan controleert.
    rommel = onderdelen.deelmap() / naam
    rommel.parent.mkdir(parents=True, exist_ok=True)
    rommel.write_bytes(b"dit is geen node")

    onderdelen._stap_node(melder=None, stop=None)
    assert (_eigen_node_pad(steunmap)).exists()
    assert hashlib.sha256((web / naam).read_bytes()).hexdigest() == sha


def test_een_archief_dat_er_al_ligt_wordt_hergebruikt(steunmap, webserver, monkeypatch):
    """Na annuleren tijdens het uitpakken hoeft de download niet opnieuw."""
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)
    naam = f"node-{NEP_VERSIE}-nepplatform.tar.gz"
    deel = onderdelen.deelmap()
    deel.mkdir(parents=True, exist_ok=True)
    (deel / naam).write_bytes((web / naam).read_bytes())
    monkeypatch.setattr(onderdelen, "NODE_BASIS", "http://127.0.0.1:1/bestaat-niet")

    onderdelen._stap_node(melder=None, stop=None)
    assert (_eigen_node_pad(steunmap)).exists()


def test_annuleren_stopt_het_ophalen(steunmap, webserver, monkeypatch):
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)
    stop = threading.Event()
    stop.set()

    with pytest.raises(onderdelen.Gestopt):
        onderdelen._stap_node(melder=None, stop=stop)
    assert not onderdelen._marker("node").exists()


# -- hyperframes -----------------------------------------------------------


def test_hyperframes_zonder_node_weigert_netjes(steunmap):
    with pytest.raises(RuntimeError, match="Node ontbreekt"):
        onderdelen._stap_hyperframes(melder=None, stop=None)


def test_hyperframes_zonder_npm_naast_node_weigert_netjes(
    steunmap, webserver, monkeypatch
):
    """Een node-archief zonder npm is een kapotte installatie, geen stille fout."""
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)   # bewust zonder npm
    onderdelen._stap_node(melder=None, stop=None)

    with pytest.raises(RuntimeError, match="npm staat niet naast node"):
        onderdelen._stap_hyperframes(melder=None, stop=None)


def test_hyperframes_dat_niet_draait_gaat_niet_voor_klaar_door(
    steunmap, webserver, monkeypatch
):
    """`npm install` kan slagen terwijl het programma daarna niet start.

    Dat is echt gebeurd: met een kale `PATH` gaf het bestand
    "env: node: No such file" en meldde `doctor` toch "ok".
    """
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch, met_npm=True)
    onderdelen._stap_node(melder=None, stop=None)
    # De nep-npm doet niets; `paths.hyperframes()` vindt dus niets.
    with pytest.raises(RuntimeError, match="draait niet"):
        onderdelen._stap_hyperframes(melder=None, stop=None)


# -- de browser ------------------------------------------------------------


def _nep_browsers(steunmap: Path, *, pad: Path | None) -> Path:
    """Een namaak-`browsers` die doet wat @puppeteer/browsers doet: een
    bestand neerzetten en het pad op de laatste regel printen."""
    bin_map = steunmap / "node_modules" / ".bin"
    bin_map.mkdir(parents=True, exist_ok=True)
    script = bin_map / "browsers"
    regel = f'echo "chrome-headless-shell@1.2.3 {pad}"' if pad else 'echo "niks"'
    maak = f'mkdir -p "{pad.parent}" && printf x > "{pad}"' if pad else "true"
    script.write_text(f"#!/bin/sh\n{maak}\n{regel}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.skipif(sys.platform.startswith("win"), reason="sh-script")
def test_de_browser_komt_uit_de_marker_en_niet_uit_een_nagebouwd_pad(steunmap):
    echt = onderdelen.chromemap() / "chrome-headless-shell" / "mac-1.2.3" / "chrome-headless-shell"
    _nep_browsers(steunmap, pad=echt)

    pad = onderdelen._stap_chrome(melder=None, stop=None)
    assert pad == echt
    assert onderdelen.chrome_pad() == echt
    assert onderdelen._marker("chrome").read_text(encoding="utf-8").strip() == str(echt)

    # Tweede keer: niets te doen, ook al is de downloader weg.
    onderdelen._marker("chrome").with_name("browsers-weg").touch()
    (steunmap / "node_modules" / ".bin" / "browsers").unlink()
    assert onderdelen._stap_chrome(melder=None, stop=None) == echt


@pytest.mark.skipif(sys.platform.startswith("win"), reason="sh-script")
def test_een_browser_die_niet_neergezet_is_geeft_een_fout(steunmap):
    _nep_browsers(steunmap, pad=None)
    with pytest.raises(RuntimeError, match="niet te vinden"):
        onderdelen._stap_chrome(melder=None, stop=None)
    assert onderdelen.chrome_pad() is None


def test_een_marker_die_naar_een_verdwenen_bestand_wijst_telt_niet(steunmap):
    onderdelen._zet_marker("chrome", f"{steunmap / 'weg' / 'chrome'}\n")
    assert onderdelen.chrome_pad() is None


def test_zonder_downloader_weigert_de_browserstap_netjes(steunmap):
    with pytest.raises(RuntimeError, match="browser-downloader"):
        onderdelen._stap_chrome(melder=None, stop=None)


def test_de_render_wijst_de_browser_hard_aan(steunmap):
    """Zonder dit zoekt HyperFrames er zelf een, midden in een render."""
    assert "HYPERFRAMES_BROWSER_PATH" not in graphics._omgeving()

    chrome = steunmap / "chrome" / "chrome-headless-shell"
    chrome.parent.mkdir(parents=True, exist_ok=True)
    chrome.write_text("x", encoding="utf-8")
    onderdelen._zet_marker("chrome", f"{chrome}\n")
    assert graphics._omgeving()["HYPERFRAMES_BROWSER_PATH"] == str(chrome)


# -- schijfruimte ----------------------------------------------------------


def test_te_weinig_ruimte_geeft_een_nette_fout_voordat_er_iets_gebeurt(
    steunmap, monkeypatch
):
    monkeypatch.setattr(onderdelen, "ruimte_vrij", lambda: 300_000_000)
    with pytest.raises(RuntimeError, match="0.3 GB vrij"):
        onderdelen.installeer()
    assert not onderdelen.gereedmap().exists()
    assert not onderdelen.nodemap().exists()


def test_ruimte_vrij_meet_de_echte_schijf(steunmap):
    assert onderdelen.ruimte_vrij() > 0


def test_alles_klaar_haalt_niets_opnieuw(steunmap, monkeypatch):
    monkeypatch.setattr(onderdelen, "status", lambda: {
        "alles_klaar": True, "ontbreekt": [], "onderdelen": []})
    assert onderdelen.installeer()["al_aanwezig"] is True


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
                    (r.get("data") or {}).get("werk") == "onderdelen":
                return r["data"]
        time.sleep(0.05)
    pytest.fail(f"geen {gebeurtenis}/onderdelen binnen {seconden} s; wel: {regels}")


def test_een_tegelijk_en_annuleren_meldt_zich(steunmap, monkeypatch, opgevangen):
    begonnen = threading.Event()

    def nep_installeer(melder=None, stop_event=None):
        if melder:
            melder("chrome", 50_000_000, 200_000_000, "Browser voor titels ophalen…")
        begonnen.set()
        stop_event.wait(10.0)
        raise onderdelen.Gestopt("gestopt")

    monkeypatch.setattr(onderdelen, "installeer", nep_installeer)

    assert _vraag("onderdelen.installeer") == {"gestart": True}
    assert begonnen.wait(5.0)
    # Tweede keer: niets gestart, want er loopt er al een.
    assert _vraag("onderdelen.installeer") == {"gestart": False}
    assert _vraag("onderdelen.status")["bezig"] is True
    assert any(w["tekst"] == "Titels klaarzetten…" for w in _vraag("bezig")["werk"])

    voortgang = _wacht_op(opgevangen, "voortgang")
    assert voortgang["stap"] == "chrome"
    assert voortgang["totaal"] == 200_000_000
    # 55 % voor de stap begint, een kwart van de laatste 45 % erbij.
    assert voortgang["percentage"] == 66

    assert _vraag("onderdelen.installeer_stop") == {"gestopt": True}
    fout = _wacht_op(opgevangen, "fout")
    assert fout["soort"] == "Gestopt"
    assert "blijft staan" in fout["fout"]
    tot = time.monotonic() + 5.0
    while onderdelen.is_bezig() and time.monotonic() < tot:
        time.sleep(0.05)
    assert onderdelen.is_bezig() is False
    assert _vraag("onderdelen.installeer_stop") == {"gestopt": False}


def test_klaar_meldt_wat_er_staat(steunmap, monkeypatch, opgevangen):
    monkeypatch.setattr(onderdelen, "installeer",
                        lambda melder=None, stop_event=None: {
                            "al_aanwezig": False, "ontbreekt": [],
                            "onderdelen": [{"naam": "chrome", "aanwezig": True}]})
    assert _vraag("onderdelen.installeer") == {"gestart": True}
    klaar = _wacht_op(opgevangen, "klaar")
    assert klaar["ontbreekt"] == []
    assert klaar["onderdelen"][0]["naam"] == "chrome"


def test_doctor_noemt_de_titelmotor_zonder_hem_als_blokkade_te_rekenen(steunmap):
    d = _vraag("doctor")
    namen = {c["naam"]: c for c in d["checks"]}
    assert namen["hyperframes"]["ok"] is False
    assert namen["hyperframes"]["vereist"] is False
    assert "geen titels" in namen["hyperframes"]["detail"]
    assert namen["chrome (headless)"]["ok"] is False


# -- wat de export meldt als de titels niet gaan -------------------------


def test_render_alle_meldt_overgeslagen_titels_in_het_resultaat(steunmap, tmp_path):
    """Stil overslaan is de fout die dit hele onderdeel heeft veroorzaakt."""
    from cve.edl import EDL, Canvas, OverlayBlok

    edl = EDL(project="x", canvas=Canvas(breedte=320, hoogte=180, fps=25))
    edl.overlay = [
        OverlayBlok(id="o-1", soort="titel", tijdlijn_start=0.0, duur=1.0,
                    inhoud={"titel": "Hallo"}),
        OverlayBlok(id="o-2", soort="titel", tijdlijn_start=1.0, duur=1.0,
                    inhoud={"titel": "Dag"}),
    ]
    waarschuwingen: list[str] = []
    uit = graphics.render_alle(edl, tmp_path, log=lambda *_: None,
                               waarschuwingen=waarschuwingen)

    assert uit == {}
    assert len(waarschuwingen) == 1
    assert "2 van de 2 titel(s)" in waarschuwingen[0]
    assert graphics.ONDERDELEN_ONTBREKEN in waarschuwingen[0]


def test_zonder_titels_komt_er_geen_waarschuwing(steunmap, tmp_path):
    from cve.edl import EDL, Canvas

    waarschuwingen: list[str] = []
    graphics.render_alle(EDL(project="x", canvas=Canvas(breedte=320, hoogte=180, fps=25)),
                         tmp_path, log=lambda *_: None, waarschuwingen=waarschuwingen)
    assert waarschuwingen == []


# -- de enige test die het internet nodig heeft ---------------------------


@pytest.mark.skipif(os.environ.get("BEATCUT_NETTEST") != "1",
                    reason="raakt het internet; zet BEATCUT_NETTEST=1")
def test_de_echte_adressen_bestaan():
    """Bestaan de gepinde node, npm-versie en Chrome-build nog? Alleen een HEAD."""
    import urllib.request

    adressen = [f"{onderdelen.NODE_BASIS}/{naam}" for naam, _ in
                onderdelen.NODE_UITGAVEN.values()]
    adressen.append(
        f"https://registry.npmjs.org/hyperframes/-/hyperframes-"
        f"{onderdelen.HYPERFRAMES_VERSIE}.tgz"
    )
    # Dezelfde plek en mapnamen waar @puppeteer/browsers hem ophaalt; zie
    # `src/browser-data/chrome-headless-shell.ts` in dat pakket.
    for plat in ("mac-arm64", "mac-x64", "win64"):
        adressen.append(
            f"https://storage.googleapis.com/chrome-for-testing-public/"
            f"{onderdelen.CHROME_VERSIE}/{plat}/chrome-headless-shell-{plat}.zip"
        )
    for url in adressen:
        verzoek = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(verzoek, timeout=60) as r:
            assert r.status == 200, url


@pytest.mark.skipif(os.environ.get("BEATCUT_NETTEST") != "1",
                    reason="raakt het internet; zet BEATCUT_NETTEST=1")
def test_de_gepinde_node_sha_klopt_met_wat_nodejs_org_zegt():
    """De sha's hier zijn met de hand overgenomen; dit betrapt een typefout."""
    import urllib.request

    url = f"{onderdelen.NODE_BASIS}/SHASUMS256.txt"
    with urllib.request.urlopen(url, timeout=60) as r:
        echt = dict(
            (regel.split()[1], regel.split()[0])
            for regel in r.read().decode("utf-8").splitlines() if regel.strip()
        )
    for naam, sha in onderdelen.NODE_UITGAVEN.values():
        assert echt.get(naam) == sha, naam


# -- de uitvoer van een hulpprogramma lezen --------------------------------


def test_de_uitvoer_van_node_wordt_als_utf8_gelezen(steunmap, tmp_path, monkeypatch):
    """Een gebruikersnaam met een accent mag het browserpad niet verminken.

    Node schrijft UTF-8. Leest Python dat met de lokale codering — cp1252 op
    een Nederlandse Windows — dan wordt `C:/Users/José/chrome.exe` ineens
    `C:/Users/JosÃ©/chrome.exe`. De browser staat er dan gewoon, maar
    `is_file()` kijkt naar het verkeerde pad en de installatie meldt zich als
    mislukt; opnieuw proberen doet precies hetzelfde.
    """
    gezien: dict = {}
    echt = subprocess.Popen

    def onthoud(cmd, **kw):
        gezien.update(kw)
        return echt(cmd, **kw)

    monkeypatch.setattr(onderdelen.subprocess, "Popen", onthoud)

    script = tmp_path / "nep-node.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('chrome@1 C:/Users/José/chrome.exe\\n'.encode('utf-8'))\n",
        encoding="utf-8",
    )
    regels = onderdelen._draai(
        [sys.executable, str(script)], cwd=tmp_path, melder=None,
        stap="chrome", tekst="proef", stop=None,
    )

    assert gezien.get("encoding") == "utf-8"
    assert regels == ["chrome@1 C:/Users/José/chrome.exe"]


def test_annuleren_stopt_ook_de_kindprocessen(steunmap, tmp_path):
    """Annuleren moet de hele boom stoppen, niet alleen het bovenste proces.

    npm start een postinstall, die start node. Dood je alleen npm, dan blijft
    de kleinzoon schrijven in de installatie én houdt hij de geërfde stdout
    open — en daar wacht `_draai()` op. De installatie blijft dan bezet tot
    die kleinzoon uit zichzelf klaar is.
    """
    script = tmp_path / "met-kind.py"
    script.write_text(
        "import subprocess, sys, time\n"
        # Een kleinzoon die stdout erft en 30 seconden blijft leven.
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print('bezig', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    klaar = threading.Event()

    def werk() -> None:
        try:
            onderdelen._draai([sys.executable, str(script)], cwd=tmp_path, melder=None,
                              stap="node", tekst="proef", stop=None)
        except (RuntimeError, onderdelen.Gestopt):
            pass
        finally:
            klaar.set()

    draad = threading.Thread(target=werk, daemon=True)
    draad.start()

    grens = time.monotonic() + 20
    while onderdelen._proces is None and time.monotonic() < grens:
        time.sleep(0.05)
    assert onderdelen._proces is not None, "het hulpprogramma startte niet"

    begin = time.monotonic()
    onderdelen.stop_installatie()
    assert klaar.wait(10), "`_draai()` bleef hangen op de kleinzoon"
    assert time.monotonic() - begin < 5


# -- een node die er al staat ----------------------------------------------


def _nep_node(map_: Path, versie: str, *, met_npm: bool = True) -> Path:
    """Een uitvoerbaar `node` dat een versie roept, met npm ernaast."""
    binmap = map_ / "bin"
    binmap.mkdir(parents=True, exist_ok=True)
    exe = binmap / "node"
    exe.write_text(f"#!/bin/sh\necho {versie}\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    if met_npm:
        (binmap / "npm").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return exe


@pytest.mark.skipif(sys.platform.startswith("win"), reason="sh-script")
def test_een_te_oude_node_telt_niet_als_klaar(steunmap, tmp_path):
    """HyperFrames eist node 22 of nieuwer.

    Npm installeert op node 18 nog wél, met een enginewaarschuwing, en pas de
    uitvoercontrole daarna faalt. Werd die node geaccepteerd, dan koos elke
    volgende poging hem opnieuw en kwam de eigen, gepinde node er nooit —
    de installatie herstelde zichzelf dus nooit.
    """
    oud = _nep_node(tmp_path / "oud", "v18.20.8")
    assert onderdelen._node_deugt(oud)[0] is False
    assert "te oud" in onderdelen._node_deugt(oud)[1]

    nieuw = _nep_node(tmp_path / "nieuw", "v24.21.0")
    assert onderdelen._node_deugt(nieuw) == (True, "v24.21.0")

    # Zonder npm ernaast is hij net zo onbruikbaar.
    kaal = _nep_node(tmp_path / "kaal", "v24.21.0", met_npm=False)
    assert onderdelen._node_deugt(kaal)[0] is False


@pytest.mark.skipif(sys.platform.startswith("win"), reason="sh-script")
def test_naast_een_te_oude_node_wordt_de_eigen_node_opgehaald(
    steunmap, tmp_path, monkeypatch
):
    oud = _nep_node(tmp_path / "oud", "v18.20.8")
    monkeypatch.setattr(paths, "node_bin", lambda: oud)

    gehaald: list[str] = []

    def nep_download(url, *a, **k):
        gehaald.append(url)
        raise RuntimeError("tot hier is genoeg")

    monkeypatch.setattr(onderdelen, "_download", nep_download)
    with pytest.raises(RuntimeError, match="tot hier is genoeg"):
        onderdelen._stap_node(melder=None, stop=None)
    assert gehaald, "de eigen node werd niet opgehaald"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="sh-script")
def test_de_eigen_node_wordt_niet_elke_keer_nagemeten(steunmap, webserver, monkeypatch):
    """Wat wij zelf met een gecontroleerde sha neerzetten, vertrouwen we.

    Anders zou elke statusvraag het nep-archief (dat geen npm meebrengt)
    afkeuren en opnieuw gaan downloaden.
    """
    web, adres = webserver
    _zet_node_klaar(web, adres, monkeypatch)
    eerste = onderdelen._stap_node(melder=None, stop=None)

    monkeypatch.setattr(onderdelen, "_download", lambda *a, **k: pytest.fail("opnieuw gehaald"))
    assert onderdelen._stap_node(melder=None, stop=None) == eerste
