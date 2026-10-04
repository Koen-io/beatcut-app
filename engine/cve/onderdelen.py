"""Node, HyperFrames en headless Chrome ophalen — de drie onderdelen die de
titels in de **export** tekenen.

**Waarom dit bestaat.** De live speler in de app tekent titels zelf in WebGPU.
De export doet het met HyperFrames: node start een headless Chrome, die rendert
de compositie, en ffmpeg legt het resultaat over de montage. Geen van die drie
zit in de installer — node en Chrome samen zijn 300 MB, en ze veranderen op een
ander tempo dan BeatCut. Zonder deze module logde `render.py` dus
"Motion graphics overgeslagen" en kwam er een video zonder titels uit, terwijl
de voorvertoning ze wél toonde. Dat is precies de belofte die niet gebroken
mag worden: **voorvertoning = export** (PLAN-v2.md §4.4).

BeatCut 1 had hiervoor `benodigdheden.zet_alles_klaar()`, maar die haalde de
nieuwste LTS op en was niet af te breken, niet te hervatten en niet te meten.
Deze module volgt het patroon van `muziekinstall.py`:

1. **Vaste versies met een gepinde sha256** waar de bron er een geeft (node).
   Een onderdeel dat zich onder onze voeten vernieuwt is een export die
   volgende maand anders kan aflopen dan vandaag.
2. **Hervatbaar en met een gereed-marker per onderdeel.** Wat er staat blijft
   staan; een afgebroken poging telt nooit als installatie.
3. **Annuleren** zet het `stop_event` en killt het kindproces.
4. **Alles in de steunmap**, niets in `~/.cache` of in de projectmap.

Chrome komt uit `@puppeteer/browsers` — dat pakket is al een afhankelijkheid
van HyperFrames, dus het staat er zodra stap 2 klaar is. Welke browser er
gebruikt wordt wijzen we daarna hard aan met `HYPERFRAMES_BROWSER_PATH`
(zie `graphics._omgeving`); dat is het enige pad dat HyperFrames vóór al zijn
eigen caches laat gaan.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import zipfile
from pathlib import Path

from . import paths
from .muziekinstall import Gestopt, _controleer, _download, _mapgrootte, _meet_groei, _meld

__all__ = [
    "Gestopt",
    "chrome_pad",
    "installeer",
    "in_achtergrond",
    "is_bezig",
    "status",
    "stop_installatie",
]

# -- wat er opgehaald wordt ------------------------------------------------

#: Vaste node-versie, geen "latest LTS". BeatCut 1 las `dist/index.json` zodat
#: het bestand niet veroudert; de prijs was dat twee installaties op twee dagen
#: een andere node krijgen. Een versie die hier staat is een versie waarop
#: getoetst is.
NODE_VERSIE = "v24.21.0"
NODE_BASIS = f"https://nodejs.org/dist/{NODE_VERSIE}"

#: Archief plus sha256 per platform, overgenomen uit `SHASUMS256.txt` naast de
#: release (nagekeken 03-10-2026). Klopt het getal niet, dan gaat het archief
#: weg en stopt de installatie.
NODE_UITGAVEN: dict[str, tuple[str, str]] = {
    "darwin-arm64": (
        f"node-{NODE_VERSIE}-darwin-arm64.tar.gz",
        "bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057",
    ),
    "darwin-x86_64": (
        f"node-{NODE_VERSIE}-darwin-x64.tar.gz",
        "1462cb3b3046b815cf8ea436d3da450ec1a9f11dac7e5a46b0ada5305d7e8097",
    ),
    "win32-x86_64": (
        f"node-{NODE_VERSIE}-win-x64.zip",
        "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
    ),
}

#: De laagste node waarmee HyperFrames draait (`engines.node` in zijn eigen
#: package.json). Npm installeert op een oudere node nog wél, met alleen een
#: enginewaarschuwing; pas het uitvoeren faalt daarna. Een node van het
#: systeem die hier niet aan voldoet halen we daarom niet binnen.
NODE_MINIMAAL = 22

#: Vaste npm-versie. npm controleert zijn eigen integriteit (`_integrity` in de
#: lockfile van het register), dus hier hoort geen eigen sha bij.
HYPERFRAMES_VERSIE = "0.8.114"

#: Dezelfde build die HyperFrames 0.8.114 zelf beheert (`CHROME_VERSION` in
#: `dist/chunk-4PFZPP2N.js`). Loopt dit uit elkaar, dan werkt het nog steeds —
#: we wijzen de browser met `HYPERFRAMES_BROWSER_PATH` hard aan — maar dan
#: tekent de export op een andere engine dan waarop HyperFrames getoetst is.
CHROME_VERSIE = "152.0.7977.30"
#: `chrome-headless-shell` en niet de volle `chrome`: dat is wat HyperFrames
#: zelf ophaalt, en het is de helft kleiner.
CHROME_BROWSER = "chrome-headless-shell"

#: Hoe groot elk onderdeel ongeveer wordt, gemeten op 03-10-2026 (macOS arm64).
#: Alleen om de balk te laten lopen: npm en de browser-downloader melden zelf
#: geen bytes.
GROOTTE: dict[str, int] = {
    "node": 110_000_000,
    "hyperframes": 120_000_000,
    "chrome": 200_000_000,
}

#: Hoeveel er vrij moet zijn voordat we beginnen: de drie onderdelen plus de
#: archieven die onderweg tijdelijk op schijf staan.
RUIMTE_NODIG = 1_200_000_000

#: Van-tot per stap, zodat de balk één keer van 0 naar 100 loopt.
STAPPEN: dict[str, tuple[int, int]] = {
    "node": (0, 30),
    "hyperframes": (30, 55),
    "chrome": (55, 100),
}

TITELS: dict[str, str] = {
    "node": "Node",
    "hyperframes": "HyperFrames",
    "chrome": "Browser voor titels",
}


# -- waar het komt te staan ------------------------------------------------


def gereedmap() -> Path:
    """Waar de markers staan die zeggen dat een onderdeel compleet is."""
    return paths.steun_map() / "onderdelen"


def deelmap() -> Path:
    """Waar een opgehaald archief blijft liggen tot de volgende poging."""
    return paths.steun_map() / "onderdelen.deel"


def nodemap() -> Path:
    return paths.steun_map() / "node"


def chromemap() -> Path:
    return paths.steun_map() / "chrome"


def _marker(naam: str) -> Path:
    return gereedmap() / f"{naam}.gereed"


def _zet_marker(naam: str, inhoud: str = "") -> None:
    """Atomair: eerst `.deel`, dan hernoemen. Een halve marker bestaat niet."""
    gereedmap().mkdir(parents=True, exist_ok=True)
    tijdelijk = _marker(naam).with_suffix(".deel")
    tijdelijk.write_text(inhoud or f"{naam} compleet\n", encoding="utf-8")
    tijdelijk.replace(_marker(naam))


def _sleutel() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x86_64"
    if sys.platform.startswith("win"):
        return "win32-x86_64"
    raise RuntimeError(
        "De titels in de export kan BeatCut alleen op macOS en Windows zelf "
        "klaarzetten. Installeer op Linux node en `npm i -g hyperframes` met de "
        "hand."
    )


def chrome_pad() -> Path | None:
    """De browser die wij hebben neergezet, of None.

    Het pad staat in de marker: `@puppeteer/browsers` bouwt een mapnaam uit
    platform en versie, en die zelf nabouwen is een regel die stil verouderd
    is zodra zij hem veranderen.
    """
    eigen = os.environ.get("BEATCUT_CHROME")
    if eigen and Path(eigen).exists():
        return Path(eigen)
    m = _marker("chrome")
    if not m.is_file():
        return None
    pad = Path(m.read_text(encoding="utf-8").strip())
    return pad if pad.is_file() else None


def ruimte_vrij() -> int:
    basis = paths.steun_map()
    basis.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(basis).free


# -- wat staat er al --------------------------------------------------------


def _hyperframes_draait() -> tuple[bool, str]:
    """Draait HyperFrames echt, of staat het er alleen?

    De vraag is niet overbodig: met een kale `PATH` — een app die vanuit
    Finder start — gaf het bestand "env: node: No such file" en meldde
    `doctor` toch "ok". Daarom met de eigen node op `PATH`, net als bij het
    renderen.
    """
    cmd = paths.hyperframes()
    if cmd is None:
        return False, ""
    from .graphics import _omgeving

    try:
        r = subprocess.run([*cmd, "--version"], capture_output=True, text=True,
                           timeout=60, env=_omgeving())
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    versie = (r.stdout or r.stderr or "").strip().splitlines()
    eerste = versie[0] if versie else ""
    if r.returncode != 0 or not eerste or eerste.startswith("env:"):
        return False, eerste
    return True, eerste


def status() -> dict:
    """Wat er staat, wat er mist, en of er een installatie loopt.

    Dit is wat de app bij het opstarten vraagt. `ontbreekt` is leeg zodra de
    export titels kan tekenen; staat er iets in, dan hoort de gebruiker dat te
    zien vóór hij op Exporteren klikt — niet achteraf in een logbestand.
    """
    node = paths.node_bin()
    draait, hf_versie = _hyperframes_draait()
    chrome = chrome_pad()
    onderdelen = [
        {
            "naam": "node",
            "titel": TITELS["node"],
            "aanwezig": node is not None,
            "pad": str(node) if node else None,
            "versie": NODE_VERSIE,
        },
        {
            "naam": "hyperframes",
            "titel": TITELS["hyperframes"],
            "aanwezig": draait,
            "pad": " ".join(paths.hyperframes() or []) or None,
            "versie": hf_versie or HYPERFRAMES_VERSIE,
        },
        {
            "naam": "chrome",
            "titel": TITELS["chrome"],
            "aanwezig": chrome is not None,
            "pad": str(chrome) if chrome else None,
            "versie": CHROME_VERSIE,
        },
    ]
    ontbreekt = [o["naam"] for o in onderdelen if not o["aanwezig"]]
    return {
        "alles_klaar": not ontbreekt,
        "ontbreekt": ontbreekt,
        "onderdelen": onderdelen,
        "bezig": is_bezig(),
        "bytes": _mapgrootte(nodemap(), chromemap(), paths.steun_map() / "node_modules"),
        "nodig_bytes": RUIMTE_NODIG,
        "uitleg": (
            "De titels in de export worden door een browser getekend. Dat is "
            "eenmalig ongeveer 400 MB ophalen; daarna werkt het offline."
        ),
    }


# -- een hulpprogramma draaien ---------------------------------------------

_proceslot = threading.Lock()
_proces: subprocess.Popen | None = None


def _onthoud(proc: subprocess.Popen | None) -> None:
    global _proces
    with _proceslot:
        _proces = proc


def _stop_boom(proc: subprocess.Popen) -> None:
    """Stop een hulpprogramma én alles wat het gestart heeft.

    npm start een postinstall, die start node. Dood je alleen npm, dan blijft
    de kleinzoon schrijven in de half-geïnstalleerde map, en hij houdt de
    geërfde stdout open — precies de pijp waar `_draai()` op staat te lezen.
    Annuleren leverde daardoor geen vrije installatie op maar een wachtende.

    Unix: het proces krijgt een eigen sessie (`start_new_session`), dus de
    procesgroep is de hele boom. Windows kent dat niet; daar loopt `taskkill`
    de boom zelf af.
    """
    if proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _omgeving_met_node() -> dict[str, str]:
    """npm en de browser-downloader moeten hun eigen node kunnen vinden."""
    omg = dict(os.environ)
    node = paths.node_bin()
    if node is not None:
        omg["PATH"] = str(node.parent) + os.pathsep + omg.get("PATH", "")
    return omg


def _draai(cmd: list[str], *, cwd: Path, melder, stap: str, tekst: str, stop) -> list[str]:
    """Draai `cmd` en geef de laatste uitvoerregels terug.

    De uitvoer van npm gaat niet naar de gebruiker — "added 73 packages" zegt
    niemand iets. Bij een fout zijn de laatste regels wél precies wat je wil
    weten, en bij de browser-downloader staat op de laatste regel het pad naar
    wat hij neergezet heeft.
    """
    _controleer(stop)
    _meld(melder, stap, 0, 0, tekst)
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=_omgeving_met_node(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
        # Expliciet UTF-8, want dat is wat node schrijft. Zonder dit decodeert
        # Python volgens de lokale codering — cp1252 op een Nederlandse
        # Windows — en wordt `C:/Users/José/chrome.exe` ineens
        # `C:/Users/JosÃ©/chrome.exe`. Dan bestaat dat bestand "niet", terwijl
        # de browser er gewoon staat, en mislukt elke volgende poging net zo.
        # `errors="replace"`: een rare byte mag de installatie niet breken.
        encoding="utf-8", errors="replace",
        # Een eigen procesgroep, zodat annuleren de hele boom raakt en niet
        # alleen npm zelf. Zie `_stop_boom()`.
        **({} if sys.platform.startswith("win") else {"start_new_session": True}),
    )
    _onthoud(proc)
    # Annuleren kan precies tussen _controleer() en _onthoud() vallen; dan zag
    # stop_installatie() nog geen proces om te killen.
    if stop is not None and stop.is_set():
        _stop_boom(proc)
    regels: list[str] = []
    try:
        assert proc.stdout is not None
        for regel in proc.stdout:
            regel = regel.strip()
            if regel:
                regels.append(regel)
                del regels[:-8]
    except BaseException:
        # Niemand leest stdout meer; zonder dit wacht `proc.wait()` hieronder
        # tot het hulpprogramma uit zichzelf klaar is.
        _stop_boom(proc)
        raise
    finally:
        proc.stdout.close()
        proc.wait()
        _onthoud(None)
    _controleer(stop)
    if proc.returncode != 0:
        raise RuntimeError(f"{tekst} mislukte: {' | '.join(regels) or 'onbekende fout'}")
    return regels


# -- de stappen ------------------------------------------------------------


def _node_deugt(exe: Path) -> tuple[bool, str]:
    """Kan deze node HyperFrames draaien? Geeft (ja/nee, uitleg of versie).

    Niet elke node is goed genoeg. Node 18 staat op veel machines op PATH, en
    HyperFrames eist 22 of nieuwer; npm installeert dan nog wel maar het
    draaien faalt. Werd zo'n node geaccepteerd, dan koos elke volgende poging
    hem opnieuw en kwam de eigen, gepinde node er nooit — de installatie
    herstelde zichzelf dus nooit.
    """
    npm = exe.parent / ("npm.cmd" if sys.platform.startswith("win") else "npm")
    if not npm.exists():
        return False, f"npm staat er niet naast ({npm})"
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    versie = (r.stdout or "").strip().splitlines()
    tekst = versie[0] if versie else ""
    cijfers = "".join(c for c in tekst.lstrip("v").split(".")[0] if c.isdigit())
    if r.returncode != 0 or not cijfers:
        return False, tekst or "geen versie"
    if int(cijfers) < NODE_MINIMAAL:
        return False, f"{tekst} is te oud; HyperFrames wil v{NODE_MINIMAAL} of nieuwer"
    return True, tekst


def _stap_node(*, melder, stop) -> Path:
    """Een eigen node in de steunmap — tenzij er al een werkende staat.

    Een node van het systeem is goed genoeg om HyperFrames te draaien, en 110
    MB ophalen voor iets dat er al staat is onvriendelijk. Hebben we er geen,
    dan halen we de gepinde versie; dan weet BeatCut precies welke hij heeft.
    """
    bestaand = paths.node_bin()
    if bestaand is not None:
        # Onze eigen node vertrouwen we op de marker: die kwam uit de gepinde
        # release met een gecontroleerde sha. Een node van het systeem meten
        # we na — zie `_node_deugt()`.
        if _marker("node").is_file() and nodemap() in bestaand.parents:
            _meld(melder, "node", 0, 0, "Node staat er al")
            return bestaand
        deugt, waarom = _node_deugt(bestaand)
        if deugt:
            _meld(melder, "node", 0, 0, f"Node staat er al ({waarom})")
            return bestaand
        _meld(melder, "node", 0, 0,
              f"De Node op deze computer kan het niet ({waarom}); "
              "BeatCut haalt zijn eigen op.")

    naam, sha = NODE_UITGAVEN[_sleutel()]
    deel = deelmap()
    deel.mkdir(parents=True, exist_ok=True)
    archief = deel / naam
    if archief.exists() and hashlib.sha256(archief.read_bytes()).hexdigest() != sha:
        # Een archief van een vorige (andere) versie of een halve kopie die
        # toch zijn echte naam kreeg: weg ermee, anders pakken we hem eeuwig op.
        archief.unlink()
    if not archief.exists():
        _download(f"{NODE_BASIS}/{naam}", archief, melder=melder, stap="node",
                  tekst="Node ophalen…", sha256=sha, stop=stop)

    _controleer(stop)
    _meld(melder, "node", 0, 0, "Node uitpakken…")
    uitpak = deel / "node-uitgepakt"
    shutil.rmtree(uitpak, ignore_errors=True)   # alleen onze eigen vorige poging
    uitpak.mkdir(parents=True)
    if archief.suffix == ".zip":
        with zipfile.ZipFile(archief) as z:
            z.extractall(uitpak)
    else:
        with tarfile.open(archief) as t:
            # `filter="data"` weigert paden buiten de doelmap en absolute
            # symlinks. De symlinks die node wél heeft (`bin/npm` naar
            # `../lib/node_modules/…`) blijven relatief en binnen het archief,
            # dus die komen er gewoon door.
            t.extractall(uitpak, filter="data")
    binnen = next((p for p in sorted(uitpak.iterdir()) if p.is_dir()), None)
    if binnen is None:
        raise RuntimeError("Het node-archief was leeg. Probeer het opnieuw.")

    doel = nodemap()
    shutil.rmtree(doel, ignore_errors=True)     # een halve node is onbruikbaar
    doel.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(binnen), str(doel))
    shutil.rmtree(deel, ignore_errors=True)     # opnieuw op te halen, dus weg mag

    exe = paths.node_bin()
    if exe is None:
        raise RuntimeError("Node is opgehaald maar er staat geen programma in de map.")
    if not sys.platform.startswith("win"):
        for p in (doel / "bin").iterdir():
            if p.is_file():
                p.chmod(p.stat().st_mode | 0o111)
        # macOS zet een quarantainevlag op alles wat je downloadt; die laat het
        # programma bij de eerste aanroep weigeren.
        if sys.platform == "darwin":
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(doel)],
                           capture_output=True, check=False)
    _zet_marker("node", f"{NODE_VERSIE}\n")
    _meld(melder, "node", 0, 0, "Node staat klaar")
    return exe


def _stap_hyperframes(*, melder, stop) -> list[str]:
    """HyperFrames met npm, in de steunmap en met onze eigen node."""
    draait, _ = _hyperframes_draait()
    if draait and _marker("hyperframes").is_file():
        _meld(melder, "hyperframes", 0, 0, "HyperFrames staat er al")
        return paths.hyperframes() or []

    node = paths.node_bin()
    if node is None:
        raise RuntimeError("Node ontbreekt; die hoort eerst opgehaald te worden.")
    npm = node.parent / ("npm.cmd" if sys.platform.startswith("win") else "npm")
    if not npm.exists():
        raise RuntimeError(f"npm staat niet naast node ({npm}).")

    basis = paths.steun_map()
    basis.mkdir(parents=True, exist_ok=True)
    if not (basis / "package.json").exists():
        (basis / "package.json").write_text(
            '{"name":"beatcut-steun","private":true}\n', encoding="utf-8"
        )

    klaar = threading.Event()
    _meet_groei((basis / "node_modules",), GROOTTE["hyperframes"], melder=melder,
                stap="hyperframes", tekst="Titelmotor installeren…", klaar=klaar)
    try:
        _draai(
            # `--ignore-scripts` niet: esbuild (een afhankelijkheid van
            # HyperFrames) heeft zijn postinstall nodig op platforms waar het
            # optionele binaire pakket niet past.
            [str(npm), "install", "--no-audit", "--no-fund",
             f"hyperframes@{HYPERFRAMES_VERSIE}"],
            cwd=basis, melder=melder, stap="hyperframes",
            tekst="Titelmotor installeren…", stop=stop,
        )
    finally:
        klaar.set()

    draait, versie = _hyperframes_draait()
    if not draait:
        raise RuntimeError(
            "HyperFrames is geïnstalleerd maar draait niet"
            + (f" ({versie})" if versie else "") + "."
        )
    _zet_marker("hyperframes", f"{versie}\n")
    _meld(melder, "hyperframes", 0, 0, "Titelmotor staat klaar")
    return paths.hyperframes() or []


def _stap_chrome(*, melder, stop) -> Path:
    """De browser die de titels tekent, via de downloader van HyperFrames zelf.

    `@puppeteer/browsers` is al een afhankelijkheid van HyperFrames, dus na
    stap 2 staat hij er. Hij schrijft naar de map die wij aanwijzen en print
    het pad naar wat hij neerzette op de laatste regel.
    """
    bestaand = chrome_pad()
    if bestaand is not None:
        _meld(melder, "chrome", 0, 0, "Browser staat er al")
        return bestaand

    basis = paths.steun_map()
    browsers = basis / "node_modules" / ".bin" / (
        "browsers.cmd" if sys.platform.startswith("win") else "browsers"
    )
    if not browsers.exists():
        raise RuntimeError(
            "De browser-downloader hoort bij HyperFrames en staat er niet; "
            "installeer dat eerst."
        )
    doel = chromemap()
    doel.mkdir(parents=True, exist_ok=True)

    klaar = threading.Event()
    _meet_groei((doel,), GROOTTE["chrome"], melder=melder, stap="chrome",
                tekst="Browser voor titels ophalen…", klaar=klaar)
    try:
        regels = _draai(
            [str(browsers), "install", f"{CHROME_BROWSER}@{CHROME_VERSIE}",
             "--path", str(doel)],
            cwd=basis, melder=melder, stap="chrome",
            tekst="Browser voor titels ophalen…", stop=stop,
        )
    finally:
        klaar.set()

    # "chrome-headless-shell@152.0.7977.30 /pad/naar/chrome-headless-shell"
    pad: Path | None = None
    for regel in reversed(regels):
        stuk = regel.split(" ", 1)
        if len(stuk) == 2 and Path(stuk[1]).is_file():
            pad = Path(stuk[1])
            break
    if pad is None:
        raise RuntimeError(
            "De browser is opgehaald maar het programma is niet te vinden: "
            + (" | ".join(regels) or "geen uitvoer")
        )
    _zet_marker("chrome", f"{pad}\n")
    _meld(melder, "chrome", 0, 0, "Browser staat klaar")
    return pad


# -- de hele installatie ---------------------------------------------------


def installeer(melder=None, stop_event=None) -> dict:
    """Alles ophalen wat de export nodig heeft om titels te tekenen.

    Blokkeert tot het klaar is. `melder(stap, gedaan, totaal, tekst)` wordt
    onderweg aangeroepen; `stop_event` is een `threading.Event` die de
    installatie met `Gestopt` afbreekt. Elke stap is los overslaanbaar: wat er
    staat blijft staan.
    """
    _sleutel()  # meteen een nette fout op een platform dat dit niet kan
    begin = status()
    if begin["alles_klaar"]:
        return {"al_aanwezig": True, "ontbreekt": [], "onderdelen": begin["onderdelen"]}

    vrij = ruimte_vrij()
    if vrij < RUIMTE_NODIG:
        raise RuntimeError(
            f"Er is {vrij / 1e9:.1f} GB vrij en er is minstens "
            f"{RUIMTE_NODIG / 1e9:.1f} GB nodig. Maak ruimte vrij en probeer het opnieuw."
        )

    _stap_node(melder=melder, stop=stop_event)
    _stap_hyperframes(melder=melder, stop=stop_event)
    _stap_chrome(melder=melder, stop=stop_event)
    _controleer(stop_event)

    eind = status()
    if not eind["alles_klaar"]:
        raise RuntimeError(
            "Klaar, maar BeatCut vindt nog niet alles: "
            + ", ".join(TITELS.get(n, n) for n in eind["ontbreekt"])
            + ". Draai het opnieuw; wat er staat blijft staan."
        )
    return {"al_aanwezig": False, "ontbreekt": [], "onderdelen": eind["onderdelen"]}


# -- in de achtergrond, één tegelijk ---------------------------------------

_bezigslot = threading.Lock()
_bezig = False
_stop: threading.Event | None = None


def is_bezig() -> bool:
    with _bezigslot:
        return _bezig


def in_achtergrond(melder=None) -> bool:
    """Start de installatie in een werkdraad. `False` als er al een loopt.

    `melder(naam, data)` krijgt dezelfde gebeurtenissen als de rest van de
    engine: `voortgang` met `werk: "onderdelen"`, daarna `klaar` of `fout`.
    """
    global _bezig, _stop
    with _bezigslot:
        if _bezig:
            return False
        _bezig = True
        _stop = threading.Event()
    stop_event = _stop

    def voortgang(stap: str, gedaan: int, totaal: int, tekst: str) -> None:
        if melder is None:
            return
        van, tot = STAPPEN.get(stap, (0, 100))
        deel = (gedaan / totaal) if totaal > 0 else 0.0
        melder("voortgang", {
            "werk": "onderdelen", "project": "", "stap": stap,
            "gedaan": gedaan, "totaal": totaal, "tekst": tekst,
            "percentage": round(van + (tot - van) * min(1.0, deel)),
        })

    def werk() -> None:
        global _bezig
        try:
            uit = installeer(melder=voortgang, stop_event=stop_event)
        except Gestopt:
            if melder:
                melder("fout", {"werk": "onderdelen", "project": "",
                                "fout": "Het klaarzetten is gestopt. "
                                        "Wat er al stond blijft staan.",
                                "soort": "Gestopt"})
            return
        except Exception as e:  # noqa: BLE001 — de app moet het horen, niet de stacktrace
            if melder:
                melder("fout", {"werk": "onderdelen", "project": "",
                                "fout": str(e), "soort": type(e).__name__})
            return
        finally:
            with _bezigslot:
                _bezig = False
        if melder:
            melder("klaar", {"werk": "onderdelen", "project": "", **uit})

    threading.Thread(target=werk, name="onderdelen", daemon=True).start()
    return True


def stop_installatie() -> bool:
    """Annuleer een lopende installatie. `False` als er niets liep."""
    with _bezigslot:
        gezet = _stop
        liep = _bezig
    if gezet is not None:
        gezet.set()
    with _proceslot:
        proc = _proces
    if proc is not None:
        _stop_boom(proc)
    return liep
