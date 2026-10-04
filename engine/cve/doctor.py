"""Controleert of alle onderdelen van de engine aanwezig en werkend zijn.

Draai met:  cve doctor
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass

from . import paths


@dataclass
class Check:
    naam: str
    ok: bool
    detail: str
    vereist: bool = True


def _run(cmd: list[str], env: dict | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"fout: {e}"


def _eerste_regel(s: str) -> str:
    return s.splitlines()[0] if s else ""


def checks() -> list[Check]:
    uit: list[Check] = []

    uit.append(
        Check(
            "platform",
            True,
            f"{platform.system()} {platform.machine()} · python {sys.version.split()[0]}",
        )
    )

    # ffmpeg / ffprobe. Via `paths._zoek_programma` en niet via `shutil.which`:
    # een app die vanuit Finder start heeft een kale PATH en vindt Homebrew
    # daar niet op. Zie de uitleg in paths.py.
    for naam in ("ffmpeg", "ffprobe"):
        p = paths._zoek_programma(naam)
        uit.append(
            Check(
                naam,
                p is not None,
                f"{_eerste_regel(_run([str(p), '-version']))} · {p}" if p
                else "niet gevonden — BeatCut haalt het op bij de eerste start",
            )
        )

    # compositor — de enige kleurweg (PLAN-v2 §4.4). Ontbreekt hij, dan rendert
    # de look via de ffmpeg-filters en wijkt de export af van stap Look. Dat is
    # een waarschuwing en geen blokkade: er komt nog steeds een video uit.
    from . import compositor

    comp = compositor.binary()
    i = compositor.info() if comp else None
    if comp is None:
        detail = compositor.waarschuwing() or (
            "niet gevonden — de look komt uit de ffmpeg-keten"
        )
    else:
        detail = (
            f"{i['versie']} · {i['adapter']} ({i['backend']}) · {comp}"
            + ("" if compositor.aan() else "  — uit via BEATCUT_COMPOSITOR=0")
        )
    uit.append(Check("compositor", comp is not None, detail, vereist=False))

    # node — alleen nodig om titels en ondertitels te tekenen. Zonder node
    # komt er gewoon een video uit, alleen zonder tekst erover. Dat is geen
    # kapotte installatie en hoort dus niet als fout te tellen.
    node = paths._zoek_programma("node")
    uit.append(
        Check(
            "node",
            node is not None,
            _run([str(node), "-v"]) if node
            else "niet gevonden — titels worden dan overgeslagen",
            vereist=False,
        )
    )

    # python-libs
    for mod, label in (
        ("cv2", "opencv"),
        ("scenedetect", "PySceneDetect"),
        ("librosa", "librosa"),
        ("numpy", "numpy"),
    ):
        try:
            m = __import__(mod)
            uit.append(Check(label, True, getattr(m, "__version__", "ok")))
        except Exception as e:  # noqa: BLE001
            uit.append(Check(label, False, str(e)))

    # whisper.cpp
    wb = paths.whisper_bin()
    uit.append(
        Check(
            "whisper.cpp",
            wb is not None,
            str(wb) if wb else "niet aanwezig — alleen nodig voor ondertitels",
            vereist=False,
        )
    )
    wm = paths.whisper_model()
    uit.append(
        Check(
            "whisper-model",
            wm is not None,
            wm.name if wm else "wordt opgehaald bij de eerste ondertiteling (1,5 GB)",
            # Geen blokkade: zonder model werkt alles behalve ondertitels, en
            # in een verse installatie is hij er per definitie nog niet.
            vereist=False,
        )
    )

    # hyperframes en de browser die de titels tekent. Via `onderdelen.status()`
    # en niet met een eigen zoektocht: deze check keek eerst alleen in
    # `node_modules` naast de repo en op PATH, en meldde daarom "nog niet
    # geinstalleerd" in een app die het keurig in zijn steunmap had staan.
    from . import onderdelen

    for o in onderdelen.status()["onderdelen"]:
        if o["naam"] == "node":
            continue    # die staat hierboven al, met zijn eigen versieregel
        uit.append(
            Check(
                "hyperframes" if o["naam"] == "hyperframes" else "chrome (headless)",
                o["aanwezig"],
                f"{o['versie']} ({o['pad']})" if o["aanwezig"]
                else "nog niet klaargezet — de export krijgt dan geen titels",
                vereist=False,
            )
        )

    # mappen. De projectmap maken we aan als hij er nog niet is: bij een verse
    # installatie bestaat hij nog niet, en dat is geen mankement maar het
    # begin.
    try:
        paths.PROJECTEN.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for d in (paths.BRANDS, paths.STYLES, paths.LOOKS, paths.PROJECTEN):
        uit.append(Check(f"map {d.name}", d.exists(), str(d)))

    return uit


def rapport() -> int:
    """Print het rapport. Geeft 0 terug als alles vereiste in orde is."""
    resultaten = checks()
    breedte = max(len(c.naam) for c in resultaten)
    fouten = 0
    print()
    for c in resultaten:
        if c.ok:
            merk = "  ok "
        elif c.vereist:
            merk = "  XX "
            fouten += 1
        else:
            merk = "  -- "
        print(f"{merk} {c.naam.ljust(breedte)}  {c.detail}")
    print()
    if fouten:
        print(f"{fouten} vereist onderdeel/onderdelen ontbreken.")
    else:
        print("Alle vereiste onderdelen aanwezig.")
    return 1 if fouten else 0
