"""ACE-Step 1.5 installeren vanuit de app — zonder git, zonder uv, zonder terminal.

`installer/muziekmodel/installeer-mac.sh` doet hetzelfde, maar dat script eist
`git` én `uv` op PATH en het draait alleen op macOS. Iemand die BeatCut uit een
installer haalt heeft geen van die twee, en hoort er ook geen terminal voor open
te hoeven trekken. Deze module haalt daarom alles zelf op:

1. **uv** als los programma uit een GitHub-release, op een vaste versie en met
   een gepinde sha256 ernaast. uv is het enige gereedschap dat nodig is: hij
   installeert zijn eigen Python 3.12 en zet de pakketten erbij.
2. **De broncode** als zip van GitHub, op een vaste commit. Een zip in plaats
   van een clone, want dan is git niet nodig.
3. **Python en de pakketten** met `uv sync`, met de Python-installatie én de
   pakketcache binnen de steunmap. Zo is de hele installatie één map en laat
   hij niets achter in `~/.cache`.
4. **De modelgewichten** (9,4 GB) met hun eigen downloader, zodat de
   bestandsnamen kloppen met wat `muziekgen.py` verwacht.

**Elke stap is hervatbaar en niets wordt ooit weggegooid.** Wat er al staat
blijft staan; uitpakken gaat eerst naar `muziekmodel.deel/` en verhuist pas als
het compleet is. Annuleren laat die halve map dus met opzet staan — de volgende
poging pakt hem weer op.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import paths
from .benodigdheden import _pak_uit

# -- wat er opgehaald wordt ------------------------------------------------

#: Vaste versie, geen "latest". Een uv die zich onder onze voeten vernieuwt is
#: een installatie die volgende maand anders kan aflopen dan vandaag.
UV_VERSIE = "0.12.22"
UV_BASIS = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSIE}"

#: Per platform het archief en zijn sha256, overgenomen van de `.sha256`-
#: bestanden naast de release (nagekeken 03-10-2026). Klopt het getal niet, dan
#: gaat het archief weg en stopt de installatie — een halve of vervangen uv is
#: erger dan geen uv.
UV_UITGAVEN: dict[str, tuple[str, str]] = {
    "darwin-arm64": (
        "uv-aarch64-apple-darwin.tar.gz",
        "5d714de09501a59393ceca78f4bc232a50478729640d251907160299b2a93ddd",
    ),
    "darwin-x86_64": (
        "uv-x86_64-apple-darwin.tar.gz",
        "1b8a5b316883df2daf20fb9a446e5b230e01d947d57aba2694977c5ac5a7e98c",
    ),
    "win32-x86_64": (
        "uv-x86_64-pc-windows-msvc.zip",
        "ea1397797a0ca15f63516dd0f49c2dde9776db9be5861cab152ebe8ad199894d",
    ),
}

#: Dezelfde commit als in `installeer-mac.sh`: het verslag van 03-10-2026
#: (`vendor/ace-step/VERSLAG.md`) is op déze code gemeten.
ACESTEP_COMMIT = "ca1e85fe9430179831e6bc6be790c332190a3866"
ACESTEP_ZIP = f"https://github.com/ace-step/ACE-Step-1.5/archive/{ACESTEP_COMMIT}.zip"
#: codeload stuurt geen Content-Length mee, dus de balk heeft een schatting
#: nodig. Gemeten op de clone: 20 MB als tar, dus een zip zit daaronder.
ACESTEP_ZIP_BYTES = 14_000_000

PYTHON_VERSIE = "3.12"          # hun pyproject eist >=3.11,<3.13
LM_MODEL = "acestep-5Hz-lm-1.7B"

#: De gewichten, gemeten op de installatie van 03-10-2026.
GEWICHTEN_BYTES = 9_400_000_000
#: Hoeveel er vrij moet zijn voordat we beginnen: 11 GB installatie plus lucht
#: voor de pakketcache en het uitpakken.
RUIMTE_NODIG = 15_000_000_000

# Hoe groot de venv plus de pakketcache ongeveer worden. Alleen om de balk te
# laten lopen tijdens `uv sync`; die stap heeft zelf geen bytes te melden.
# ponytail: ruwe schatting, de balk wordt op het stapmaximum afgekapt.
VENV_BYTES = 6_000_000_000 if sys.platform.startswith("win") else 2_500_000_000

#: Van-tot per stap, zodat de balk één keer van 0 naar 100 loopt in plaats van
#: vier keer. De gewichten zijn de wachttijd, niet het aantal bytes.
STAPPEN: dict[str, tuple[int, int]] = {
    "uv": (0, 2),
    "code": (2, 6),
    "python": (6, 28),
    "gewichten": (28, 100),
}


class Gestopt(RuntimeError):
    """De gebruiker heeft op Annuleren gedrukt."""


# -- waar het komt te staan ------------------------------------------------


def doelmap() -> Path:
    """De map die `paths.muziekmodel()` straks moet vinden."""
    return paths.steun_map() / "muziekmodel"


def deelmap() -> Path:
    """Waar een halve download blijft liggen tot de volgende poging."""
    return paths.steun_map() / "muziekmodel.deel"


def uv_pad() -> Path | None:
    exe = "uv.exe" if sys.platform.startswith("win") else "uv"
    p = paths.steun_map() / "bin" / exe
    return p if p.exists() else None


def _sleutel() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x86_64"
    if sys.platform.startswith("win"):
        return "win32-x86_64"
    raise RuntimeError(
        "Het muziekmodel kan BeatCut alleen op macOS en Windows zelf installeren. "
        "Gebruik op Linux installer/muziekmodel/installeer-mac.sh als voorbeeld."
    )


def ruimte_vrij() -> int:
    """Hoeveel bytes er vrij zijn op de schijf waar de installatie komt."""
    basis = paths.steun_map()
    basis.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(basis).free


# -- voortgang en annuleren ------------------------------------------------


def _meld(melder, stap: str, gedaan: int, totaal: int, tekst: str) -> None:
    if melder is not None:
        melder(stap, gedaan, totaal, tekst)


def _controleer(stop) -> None:
    if stop is not None and stop.is_set():
        raise Gestopt("De installatie is gestopt.")


def _mapgrootte(*mappen: Path) -> int:
    totaal = 0
    for d in mappen:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    totaal += p.stat().st_size
            except OSError:
                continue
    return totaal


def _meet_groei(mappen: tuple[Path, ...], verwacht: int, *, melder, stap: str,
                tekst: str, klaar: threading.Event) -> threading.Thread:
    """Meldt elke paar seconden hoe groot de mappen zijn geworden.

    `uv sync` en de modeldownloader vertellen zelf niet hoe ver ze zijn in
    bytes. Wat ze wél doen is de schijf vullen, en dat is te meten.
    """

    def kijken() -> None:
        while not klaar.wait(3.0):
            gedaan = min(_mapgrootte(*mappen), verwacht)
            _meld(melder, stap, gedaan, verwacht, tekst)

    t = threading.Thread(target=kijken, name=f"muziekinstall-{stap}", daemon=True)
    t.start()
    return t


# -- ophalen ---------------------------------------------------------------


def _download(url: str, doel: Path, *, melder, stap: str, tekst: str,
              sha256: str | None = None, verwacht: int = 0, stop=None) -> Path:
    """Haal `url` op naar `doel`, met voortgang en desgewenst een sha-controle.

    Schrijven gaat naar `<doel>.deel`; pas als het bestand compleet én goed is
    krijgt het zijn echte naam. Een afgebroken download kan zo nooit voor een
    goede doorgaan.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    deel = doel.with_name(doel.name + ".deel")
    h = hashlib.sha256()
    gedaan = 0
    laatst = 0.0
    with urllib.request.urlopen(url, timeout=120) as r:
        totaal = int(r.headers.get("Content-Length") or 0) or verwacht
        _meld(melder, stap, 0, totaal, tekst)
        with deel.open("wb") as f:
            while True:
                _controleer(stop)
                blok = r.read(1 << 18)
                if not blok:
                    break
                f.write(blok)
                h.update(blok)
                gedaan += len(blok)
                nu = time.monotonic()
                if nu - laatst > 0.25:
                    laatst = nu
                    _meld(melder, stap, gedaan, max(totaal, gedaan), tekst)
    if sha256 is not None and h.hexdigest() != sha256:
        deel.unlink(missing_ok=True)
        raise RuntimeError(
            f"De download van {doel.name} is onderweg beschadigd "
            "(het controlegetal klopt niet). Probeer het later opnieuw."
        )
    deel.replace(doel)
    _meld(melder, stap, gedaan, max(totaal, gedaan), tekst)
    return doel


def _stap_uv(*, melder, stop) -> Path:
    bestaand = uv_pad()
    if bestaand is not None:
        _meld(melder, "uv", 0, 0, "Gereedschap staat er al")
        return bestaand
    naam, sha = UV_UITGAVEN[_sleutel()]
    with tempfile.TemporaryDirectory(prefix="beatcut-uv-") as tmp:
        archief = _download(
            f"{UV_BASIS}/{naam}", Path(tmp) / naam, melder=melder, stap="uv",
            tekst="Gereedschap ophalen…", sha256=sha, stop=stop,
        )
        _pak_uit(archief, paths.steun_map() / "bin", ("uv", "uvx"), log=lambda *_: None)
    p = uv_pad()
    if p is None:
        raise RuntimeError("Het gereedschap is opgehaald maar zat niet in het archief.")
    return p


def _stap_code(*, melder, stop) -> Path:
    """De broncode op de vaste commit, uitgepakt in `doelmap()`."""
    doel = doelmap()
    if (doel / "acestep").is_dir() and (doel / "pyproject.toml").exists():
        _meld(melder, "code", 0, 0, "Broncode staat er al")
        return doel

    deel = deelmap()
    deel.mkdir(parents=True, exist_ok=True)
    zip_pad = deel / "broncode.zip"
    if not (zip_pad.exists() and zipfile.is_zipfile(zip_pad)):
        _download(ACESTEP_ZIP, zip_pad, melder=melder, stap="code",
                  tekst="Broncode ophalen…", verwacht=ACESTEP_ZIP_BYTES, stop=stop)

    _controleer(stop)
    _meld(melder, "code", 0, 0, "Broncode uitpakken…")
    uitpak = deel / "uitgepakt"
    shutil.rmtree(uitpak, ignore_errors=True)   # alleen onze eigen vorige poging
    with zipfile.ZipFile(zip_pad) as z:
        z.extractall(uitpak)
    binnen = next((p for p in sorted(uitpak.iterdir()) if p.is_dir()), None)
    if binnen is None:
        raise RuntimeError("Het broncode-archief was leeg. Probeer het opnieuw.")

    if doel.exists():
        # Een halve map van een eerdere poging: erin kopiëren, niet eroverheen
        # met een nieuwe map. Een venv of al opgehaalde gewichten die er staan
        # blijven zo staan.
        shutil.copytree(binnen, doel, dirs_exist_ok=True)
    else:
        doel.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(binnen), str(doel))
    shutil.rmtree(deel, ignore_errors=True)     # opnieuw op te halen, dus weg mag
    _meld(melder, "code", 0, 0, "Broncode staat klaar")
    return doel


# -- draaien ---------------------------------------------------------------

_proceslot = threading.Lock()
_proces: subprocess.Popen | None = None


def _onthoud(proc: subprocess.Popen | None) -> None:
    """Welk kindproces er nu loopt, zodat `stop_installatie()` het kan killen."""
    global _proces
    with _proceslot:
        _proces = proc


def _uv_omgeving(doel: Path) -> dict[str, str]:
    """De omgeving voor uv: alles binnen de steunmap, niets uit onze eigen venv.

    `VIRTUAL_ENV` moet eruit. Draait BeatCut vanuit de broncode, dan staat die
    op de venv van BeatCut zelf en zou uv in die venv gaan synchroniseren — en
    daar hoort torch niet.
    """
    omg = dict(os.environ)
    basis = paths.steun_map()
    omg["UV_PYTHON_INSTALL_DIR"] = str(basis / "uv" / "python")
    omg["UV_CACHE_DIR"] = str(basis / "uv" / "cache")
    omg["UV_NO_PROGRESS"] = "1"      # anders carriage returns in plaats van regels
    omg["UV_PROJECT_ENVIRONMENT"] = str(doel / ".venv")
    omg["HF_HOME"] = str(doel / "hf")
    for v in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX"):
        omg.pop(v, None)
    return omg


def _draai(cmd: list[str], *, cwd: Path, omg: dict[str, str], melder, stap: str,
           tekst: str, stop) -> None:
    """Een hulpprogramma draaien; zijn uitvoer bewaren voor als het misgaat.

    Het proces wordt onthouden: annuleren gebeurt door het te killen, niet door
    op een regel te wachten die misschien nooit komt.

    De uitvoer van uv gaat niet naar de gebruiker. "Resolved 243 packages in
    1.2s" zegt niemand iets; wat er in de balk hoort is waar we mee bezig zijn,
    en dat staat in `tekst`. Bij een fout zijn de laatste regels wél precies
    wat je wil weten.
    """
    _controleer(stop)
    _meld(melder, stap, 0, 0, tekst)
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=omg, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    _onthoud(proc)
    # Annuleren kan precies tussen _controleer() en _onthoud() vallen; dan zag
    # stop_installatie() nog geen proces om te killen (codex-review 03-10, #13).
    if stop is not None and stop.is_set():
        proc.kill()
    laatste: list[str] = []
    try:
        assert proc.stdout is not None
        for regel in proc.stdout:
            regel = regel.strip()
            if not regel:
                continue
            laatste.append(regel)
            del laatste[:-4]
    finally:
        proc.wait()
        _onthoud(None)
    _controleer(stop)
    if proc.returncode != 0:
        reden = " | ".join(laatste) or "onbekende fout"
        raise RuntimeError(f"{tekst} mislukte: {reden}")


def _stap_python(uv: Path, doel: Path, *, melder, stop) -> Path:
    """Python 3.12 en alle pakketten, allemaal binnen de steunmap."""
    omg = _uv_omgeving(doel)
    _draai([str(uv), "python", "install", PYTHON_VERSIE], cwd=doel, omg=omg,
           melder=melder, stap="python", tekst="Python installeren…", stop=stop)

    # Torch en op de Mac ook mlx: samen ruim een gigabyte. De balk loopt mee op
    # wat er op schijf verschijnt, want uv meldt zelf geen bytes.
    klaar = threading.Event()
    _meet_groei((doel / ".venv", paths.steun_map() / "uv"), VENV_BYTES,
                melder=melder, stap="python", tekst="Pakketten installeren…", klaar=klaar)
    try:
        _draai([str(uv), "sync", "--python", PYTHON_VERSIE], cwd=doel, omg=omg,
               melder=melder, stap="python", tekst="Pakketten installeren…", stop=stop)
    finally:
        klaar.set()

    py = paths.muziekmodel_python(doel)
    if py is None:
        raise RuntimeError(
            f"De pakketten zijn geïnstalleerd maar er staat geen Python in {doel / '.venv'}."
        )
    return py


#: Draait in de venv van ACE-Step, niet in die van BeatCut.
#:
#: **`ensure_model` bestaat niet** — `installer/muziekmodel/installeer-mac.sh`
#: riep die aan en kreeg een ImportError (gemeten 03-10-2026 door de stap echt
#: te draaien). Het heet `ensure_main_model`, en die haalt het DiT-model, de
#: vae, de tekst-encoder én het 1,7B-taalmodel in één keer. `ensure_lm_model`
#: blijft erachteraan staan als vangnet; staat het er al, dan doet hij niets.
#:
#: En ze geven `(gelukt, bericht)` terug in plaats van een uitzondering. Zonder
#: dat zelf te toetsen zou de app "klaar" melden bij een lege checkpoints-map.
_HAAL_SRC = f"""
import os, sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from acestep.model_downloader import ensure_lm_model, ensure_main_model

CP = Path(os.getcwd()) / "checkpoints"
for naam, (gelukt, bericht) in (
    ("Het model", ensure_main_model(checkpoints_dir=CP)),
    ("Het taalmodel", ensure_lm_model({LM_MODEL!r}, checkpoints_dir=CP)),
):
    print(naam + ": " + str(bericht))
    if not gelukt:
        raise SystemExit(naam + " ophalen mislukte: " + str(bericht))
print("gewichten staan klaar")
"""


def _stap_gewichten(py: Path, doel: Path, *, melder, stop) -> None:
    klaar = threading.Event()
    _meet_groei((doel / "checkpoints", doel / "hf"), GEWICHTEN_BYTES,
                melder=melder, stap="gewichten", tekst="Modelgewichten ophalen…",
                klaar=klaar)
    try:
        _draai([str(py), "-c", _HAAL_SRC], cwd=doel, omg=_uv_omgeving(doel),
               melder=melder, stap="gewichten", tekst="Modelgewichten ophalen…", stop=stop)
    finally:
        klaar.set()


# -- de hele installatie ---------------------------------------------------


def installeer(melder=None, stop_event=None) -> dict:
    """Alles ophalen wat `muziekgen.py` nodig heeft. Blokkeert tot het klaar is.

    `melder(stap, gedaan, totaal, tekst)` wordt onderweg aangeroepen; `gedaan`
    en `totaal` zijn bytes waar dat te meten is en anders 0. `stop_event` is een
    `threading.Event`: zodra die gezet is stopt de installatie met `Gestopt`.
    """
    _sleutel()  # meteen een nette fout op een platform dat dit niet kan
    staat_er = paths.muziekmodel()
    if staat_er is not None:
        return {"al_aanwezig": True, "pad": str(staat_er), "bytes": _mapgrootte(staat_er)}

    vrij = ruimte_vrij()
    if vrij < RUIMTE_NODIG:
        raise RuntimeError(
            f"Er is {vrij / 1e9:.1f} GB vrij en er is minstens "
            f"{RUIMTE_NODIG / 1e9:.0f} GB nodig. Maak ruimte vrij en probeer het opnieuw."
        )

    uv = _stap_uv(melder=melder, stop=stop_event)
    doel = _stap_code(melder=melder, stop=stop_event)
    py = _stap_python(uv, doel, melder=melder, stop=stop_event)
    _stap_gewichten(py, doel, melder=melder, stop=stop_event)
    _controleer(stop_event)
    # Pas nu is het af: atomair de gereed-marker, zodat een afgebroken
    # download nooit als installatie telt en altijd hervat wordt.
    marker = doel / paths.MUZIEKMODEL_GEREED
    tijdelijk = marker.with_suffix(".deel")
    tijdelijk.write_text("ACE-Step 1.5 compleet\n", encoding="utf-8")
    tijdelijk.replace(marker)

    gevonden = paths.muziekmodel()
    if gevonden is None:
        raise RuntimeError(
            f"De installatie in {doel} is klaar maar BeatCut vindt hem niet. "
            "Mist er een onderdeel? Draai het opnieuw; wat er staat blijft staan."
        )
    return {"al_aanwezig": False, "pad": str(gevonden), "bytes": _mapgrootte(gevonden)}


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
    engine: `voortgang` met `werk: "muziekinstall"`, daarna `klaar` of `fout`.
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
            "werk": "muziekinstall", "project": "", "stap": stap,
            "gedaan": gedaan, "totaal": totaal, "tekst": tekst,
            "percentage": round(van + (tot - van) * min(1.0, deel)),
        })

    def werk() -> None:
        global _bezig
        try:
            uit = installeer(melder=voortgang, stop_event=stop_event)
        except Gestopt:
            if melder:
                melder("fout", {"werk": "muziekinstall", "project": "",
                                "fout": "De installatie is gestopt. "
                                        "Wat er al stond blijft staan.",
                                "soort": "Gestopt"})
            return
        except Exception as e:  # noqa: BLE001 — de app moet het horen, niet de stacktrace
            if melder:
                melder("fout", {"werk": "muziekinstall", "project": "",
                                "fout": str(e), "soort": type(e).__name__})
            return
        finally:
            with _bezigslot:
                _bezig = False
        if melder:
            melder("klaar", {"werk": "muziekinstall", "project": "", **uit})

    threading.Thread(target=werk, name="muziekinstall", daemon=True).start()
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
    if proc is not None and proc.poll() is None:
        proc.kill()
    return liep
