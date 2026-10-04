"""Padbeheer. Cross-platform, geen hardcoded scheidingstekens.

Alle paden in de engine lopen via deze module. Windows-veiligheid begint hier.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

def _wortel() -> Path:
    """Waar `studio/`, `styles/` en `brands/` staan.

    Drie situaties, en ze zijn alle drie echt:

    - **Vanuit de broncode**: twee mappen boven dit bestand.
    - **Ingevroren met PyInstaller**: de bestanden zitten in de bundel, en
      die pakt hij uit in `sys._MEIPASS`.
    - **Zelf een plek aanwijzen** met `CVE_ROOT`. Handig bij het testen van
      een build, en nodig als iemand de projectmap ergens anders wil hebben.
    """
    eigen = os.environ.get("CVE_ROOT")
    if eigen and Path(eigen).exists():
        return Path(eigen).resolve()
    bundel = getattr(sys, "_MEIPASS", None)
    if bundel and (Path(bundel) / "studio").exists():
        return Path(bundel)
    return Path(__file__).resolve().parents[2]


ROOT = _wortel()

BRANDS = ROOT / "brands"
STYLES = ROOT / "styles"
VENDOR = ROOT / "vendor"
LOOKS = ROOT / "looks"
SKILLS = ROOT / "skills"


def _projecten() -> Path:
    """Waar de video's van de gebruiker staan.

    Vanuit de broncode gewoon naast de engine. Maar een geïnstalleerde app
    staat in Programma's, en daar hoort niemands vakantievideo thuis - dan
    gaan ze naar de Films-map, waar je ze ook terugvindt zonder deze app.
    """
    eigen = os.environ.get("CVE_PROJECTEN")
    if eigen:
        return Path(eigen).expanduser().resolve()
    if getattr(sys, "frozen", False):
        thuis = Path.home()
        films = thuis / ("Movies" if sys.platform == "darwin" else "Videos")
        return (films if films.exists() else thuis) / "BeatCut"
    return ROOT / "projecten"


PROJECTEN = _projecten()


def project_dir(naam: str) -> Path:
    """Map van een videoproject. Maakt hem aan als hij nog niet bestaat."""
    p = PROJECTEN / naam
    for sub in ("bronnen", "proxies", "composities", "renders", "cache"):
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p


def which(naam: str) -> Path | None:
    """Zoek een uitvoerbaar bestand op PATH. Werkt op macOS, Linux en Windows."""
    from shutil import which as _which

    hit = _which(naam)
    return Path(hit) if hit else None


def steun_map() -> Path:
    """Waar de app dingen bewaart die hij zelf ophaalt: ffmpeg, modellen.

    `BEATCUT_STEUN` wijst een andere map aan. Dat is er voor de tests en voor
    het natrekken van een installatie: zonder die uitweg schrijft elke proef
    in de echte steunmap van Koen, en dan toets je nooit een verse machine.
    """
    eigen = os.environ.get("BEATCUT_STEUN")
    if eigen:
        return Path(eigen).expanduser().resolve()
    if sys.platform == "darwin":
        basis = Path.home() / "Library" / "Application Support" / "BeatCut"
    elif sys.platform.startswith("win"):
        basis = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BeatCut"
    else:
        basis = Path.home() / ".local" / "share" / "beatcut"
    return basis


def _meegeleverde_mappen() -> list[Path]:
    """Mappen waar een ffmpeg staat die bij déze BeatCut hoort.

    - **Ingevroren app**: de installer zet `ffmpeg` en `ffprobe` naast het
      engine-programma in `BeatCut.app/Contents/Resources/engine/bin/`
      (op Windows `<map van de exe>\\engine\\bin\\`). `sys.executable` wijst
      dan naar het engine-programma zelf, dus de map ernaast.
    - **Vanuit de broncode**: wat `installer/ffmpeg/bouw-mac.sh` opleverde, en
      `installer/uit/compositor/` voor het compositor-binary. Zo draaien de
      tests op dezelfde hulpprogramma's als de gebruiker krijgt. Uitzondering:
      `compositor.binary()` kijkt in de ontwikkelboom éérst in
      `compositor/target/release/`, zodat een oude kopie hier een verse
      `cargo build --release` niet kan overschaduwen.

    De compositor hoort hier en niet in de PyInstaller-bundel, om dezelfde
    reden als ffmpeg: PyInstaller herschrijft bibliotheekpaden in alles wat via
    `binaries` meegaat, en dat heeft een los uitvoerbaar bestand niet nodig.
    """
    mappen: list[Path] = []
    if getattr(sys, "frozen", False):
        mappen.append(Path(sys.executable).resolve().parent / "bin")
    mappen += [
        ROOT / "bin",
        ROOT / "installer" / "uit" / "ffmpeg" / "huidig",
        ROOT / "installer" / "uit" / "compositor",
    ]
    return mappen


def _zoek_programma(naam: str) -> Path | None:
    """Zoek een hulpprogramma op alle plekken waar het kan staan.

    **PATH alleen is niet genoeg.** Een app die je vanuit Finder start krijgt
    een kale omgeving mee - `/usr/bin:/bin:/usr/sbin:/sbin` - en Homebrew
    installeert in `/opt/homebrew/bin`. Dat betekent dat ffmpeg wél op de
    computer staat en de app hem tóch niet vindt. Hier is dat drie keer op
    stukgelopen voordat het opviel; vandaar deze lijst.
    """
    exe = f"{naam}.exe" if sys.platform.startswith("win") else naam

    # 1. Zelf aangewezen
    eigen = os.environ.get(f"CVE_{naam.upper()}")
    if eigen and Path(eigen).exists():
        return Path(eigen)

    plekken = [
        # 2. Meegeleverd met de app - die gaat voor, ook boven Homebrew.
        #    Het is onze eigen LGPL-build (installer/ffmpeg/bouw-mac.sh); een
        #    ffmpeg van het systeem is meestal GPL en kan andere filters of
        #    een andere versie hebben dan waarop getoetst is.
        *[d / exe for d in _meegeleverde_mappen()],
        # 3. Wat de app zelf heeft opgehaald bij de eerste start
        steun_map() / "bin" / exe,
    ]
    if sys.platform == "darwin":
        plekken += [
            Path("/opt/homebrew/bin") / exe,   # Homebrew op Apple silicon
            Path("/usr/local/bin") / exe,      # Homebrew op Intel
            Path("/opt/local/bin") / exe,      # MacPorts
        ]
    elif sys.platform.startswith("win"):
        for schijf in ("C:/", "C:/Program Files/"):
            plekken.append(Path(schijf) / "ffmpeg" / "bin" / exe)
    else:
        plekken += [Path("/usr/bin") / exe, Path("/usr/local/bin") / exe]

    for p in plekken:
        if p.exists():
            return p
    # 4. Pas als laatste: gewoon op PATH
    return which(naam)


def ffmpeg() -> Path:
    p = _zoek_programma("ffmpeg")
    if p is None:
        raise RuntimeError(
            "ffmpeg is niet gevonden. Open BeatCut en klik op 'ffmpeg ophalen', "
            "of installeer het zelf met: brew install ffmpeg"
        )
    return p


def ffprobe() -> Path:
    p = _zoek_programma("ffprobe")
    if p is None:
        raise RuntimeError(
            "ffprobe is niet gevonden. Die hoort bij ffmpeg; haal ffmpeg op in "
            "BeatCut of installeer het met: brew install ffmpeg"
        )
    return p


def heeft_ffmpeg() -> bool:
    return _zoek_programma("ffmpeg") is not None and _zoek_programma("ffprobe") is not None


def node_bin() -> Path | None:
    """De Node die BeatCut gebruikt: eerst zijn eigen, dan die van het systeem."""
    exe = "node.exe" if sys.platform.startswith("win") else "node"
    eigen = steun_map() / "node"
    for p in (eigen / exe, eigen / "bin" / exe):
        if p.exists():
            return p
    return _zoek_programma("node")


def hyperframes() -> list[str] | None:
    """Het commando om HyperFrames te draaien, of None als het er niet is.

    Volgorde: wat BeatCut zelf heeft opgehaald, dan de projectmap, dan het
    systeem. De eerste is wat een geïnstalleerde app gebruikt.
    """
    exe = "hyperframes.cmd" if sys.platform.startswith("win") else "hyperframes"
    for basis in (steun_map(), ROOT):
        p = basis / "node_modules" / ".bin" / exe
        if p.exists():
            return [str(p)]
    gevonden = which("hyperframes")
    if gevonden:
        return [str(gevonden)]
    return None


def whisper_bin() -> Path | None:
    """whisper.cpp binary. Eerst env-var, dan vendor-map, dan PATH."""
    env = os.environ.get("CVE_WHISPER_BIN")
    if env and Path(env).exists():
        return Path(env)
    exe = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    lokaal = VENDOR / "whisper.cpp" / "build" / "bin" / exe
    if lokaal.exists():
        return lokaal
    return which("whisper-cli")


def whisper_model() -> Path | None:
    env = os.environ.get("CVE_WHISPER_MODEL")
    if env and Path(env).exists():
        return Path(env)
    d = VENDOR / "whisper.cpp" / "models"
    if d.exists():
        # Voorkeursvolgorde; "for-tests-" modellen zijn dummy's en tellen niet mee.
        voorkeur = ("large-v3-turbo", "large-v3", "large", "medium", "small", "base")
        echte = [p for p in d.glob("ggml-*.bin") if not p.name.startswith("for-tests")]
        for naam in voorkeur:
            for p in echte:
                if p.stem == f"ggml-{naam}":
                    return p
        if echte:
            return max(echte, key=lambda p: p.stat().st_size)
    return None


def muziekmodel_python(wortel: Path) -> Path | None:
    """De Python van de ACE-Step-venv. Die heeft torch; onze engine nooit."""
    for sub in (("bin", "python3"), ("bin", "python"), ("Scripts", "python.exe")):
        p = wortel.joinpath(".venv", *sub)
        if p.exists():
            return p
    return None


# Gezet door `muziekinstall` (en installeer-mac.sh) als álle gewichten er zijn.
MUZIEKMODEL_GEREED = ".beatcut-gereed"


def muziekmodel() -> Path | None:
    """Waar ACE-Step 1.5 staat, of None als het er niet is.

    Twee plekken, in deze volgorde: wat de app zelf heeft opgehaald in de
    steunmap, en de ontwikkelkopie in `vendor/ace-step`. De eerste gaat voor,
    zodat een geïnstalleerde app nooit per ongeluk aan de werkmap hangt.

    Een map telt alleen mee als hij compleet is: eigen venv (met torch) én de
    modelgewichten. Een halve clone is erger dan geen clone — dan start het
    serverproces wel en faalt het pas na vijftien seconden.
    """
    eigen = os.environ.get("BEATCUT_MUZIEKMODEL")
    kandidaten = [Path(eigen).expanduser()] if eigen else []
    kandidaten += [steun_map() / "muziekmodel", VENDOR / "ace-step"]
    beheerd = steun_map() / "muziekmodel"
    for d in kandidaten:
        if (d / "acestep").is_dir() and muziekmodel_python(d) is not None:
            if (d / "checkpoints" / "acestep-v15-turbo").is_dir():
                # De map die de app zelf vult telt pas als de installatie tot
                # het eind kwam: een afgebroken download heeft de modelmap al,
                # maar niet alle gewichten (codex-review 03-10, #12).
                if d == beheerd and not (d / MUZIEKMODEL_GEREED).is_file():
                    continue
                return d
    return None
