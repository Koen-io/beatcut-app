# PyInstaller-recept voor de BeatCut-engine.
#
#     .venv/bin/pyinstaller installer/beatcut.spec --noconfirm
#
# Levert `installer/uit/beatcut-engine/` op: de complete engine zonder dat er
# een Python op de computer hoeft te staan. Dat is wat de installer straks
# meeneemt.
#
# Drie dingen die niet vanzelf goed gaan en hier daarom expliciet staan:
#
# 1. **De interface zit niet in de code.** `studio/`, `styles/` en `brands/`
#    zijn gewone bestanden die de engine bij het draaien inleest. PyInstaller
#    ziet die niet; zonder `datas` start hij op en vindt hij niets.
#
# 2. **numba en librosa laden hun onderdelen pas tijdens het draaien.**
#    Een importscan mist die. Vandaar `hiddenimports` en `collect_all`.
#
# 3. **ffmpeg, de compositor en whisper.cpp zitten hier niet in, maar wel in
#    de app.**
#    Sinds 02-10-2026 bouwt `installer/ffmpeg/bouw-mac.sh` een eigen
#    LGPL-ffmpeg, en Tauri zet die als bundle-resource in
#    `Contents/Resources/engine/bin/` - dus naast het programma dat deze spec
#    oplevert, niet erin. `paths._meegeleverde_mappen()` kijkt daar als
#    eerste. Dat het buiten de PyInstaller-bundel blijft is geen toeval:
#    PyInstaller herschrijft bibliotheekpaden in alles wat via `binaries`
#    meegaat, en dat heeft een los uitvoerbaar bestand niet nodig.
#    whisper.cpp is nog steeds los - 1,5 GB model voor alleen ondertitels.
#    Hetzelfde geldt sinds 03-10-2026 voor `beatcut-compositor`: de CI bouwt
#    de crate naar `installer/uit/compositor/` en Tauri zet die map ook in
#    `engine/bin/`, naast ffmpeg. `paths._meegeleverde_mappen()` vindt beide.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

WORTEL = Path(SPECPATH).resolve().parent

verborgen = []
extra_datas = []
extra_binaries = []
for pakket in ("librosa", "numba", "llvmlite", "scenedetect", "soxr", "soundfile"):
    try:
        d, b, h = collect_all(pakket)
        extra_datas += d
        extra_binaries += b
        verborgen += h
    except Exception:  # noqa: BLE001
        pass
verborgen += collect_submodules("cve")

a = Analysis(
    [str(WORTEL / "installer" / "start_engine.py")],
    pathex=[str(WORTEL / "engine")],
    binaries=extra_binaries,
    datas=[
        (str(WORTEL / "studio"), "studio"),
        (str(WORTEL / "styles"), "styles"),
        (str(WORTEL / "brands"), "brands"),
        (str(WORTEL / "looks"), "looks"),
        # Plaatsnamen voor de titels (GeoNames, CC BY 4.0 — zie DERDEN.md).
        # Zonder deze lijst vindt een geïnstalleerde app geen enkele titel.
        *([(str(WORTEL / "vendor" / "geonames"), "vendor/geonames")]
          if (WORTEL / "vendor" / "geonames" / "plaatsen.tsv").exists() else []),
        (str(WORTEL / "installer" / "DERDEN.md"), "."),
        *extra_datas,
    ],
    hiddenimports=verborgen,
    hookspath=[],
    runtime_hooks=[],
    # Wat de engine nooit gebruikt en wat anders honderden megabytes kost.
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6", "IPython",
              "notebook", "pytest", "sphinx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="beatcut-engine",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="beatcut-engine",
)
