"""Het spraakmodel ophalen, zodat ondertitels ook in de app werken (15-10-2026).

**Waarom dit bestaat.** `spraak.py` heeft twee dingen nodig: `whisper-cli` en
een model. Vanuit de broncode staan beide in `vendor/whisper.cpp/`. In de app
stond geen van beide, en de spraakkaart zei alleen "Spraakherkenning staat
niet op deze computer" — zonder knop, zonder uitweg. Gezien bij de eerste
echte klikronde.

`whisper-cli` gaat nu statisch gelinkt mee in de app
(`installer/whisper/bouw-mac.sh` → `Contents/Resources/engine/whisper/`).
Het model is te groot voor de installer en wordt hier bij het eerste gebruik
opgehaald, met dezelfde `_download` als het muziekmodel: naar `.deel`,
sha256-gecontroleerd, pas daarna onder zijn echte naam.

Welk model: **large-v3-turbo, q5_0** (574 MB). Dezelfde turbo als in de
ontwikkelboom (1,6 GB), gekwantiseerd; whisper.cpp levert hem zo zelf aan en
het verschil in herkenning is voor ondertitels niet te horen, het verschil in
download wel.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import paths
from .muziekinstall import Gestopt, _download

MODEL = "ggml-large-v3-turbo-q5_0.bin"
URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{MODEL}"
#: Uit de Git-LFS-pointer op Hugging Face (nagekeken 15-10-2026).
SHA256 = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"
GROOTTE = 574_041_195
#: Model plus ruimte voor het `.deel`-bestand dat er tijdelijk naast staat.
RUIMTE_NODIG = 700_000_000

_slot = threading.Lock()
_draad: threading.Thread | None = None
_stop = threading.Event()


def modelmap() -> Path:
    return paths.steun_map() / "whisper" / "models"


def is_bezig() -> bool:
    return _draad is not None and _draad.is_alive()


def status() -> dict:
    return {
        "bin": paths.whisper_bin() is not None,
        "model": paths.whisper_model() is not None,
        "bezig": is_bezig(),
        "bytes": GROOTTE,
    }


def installeer(melder=None, stop_event: threading.Event | None = None) -> Path:
    """Haal het model op. Synchroon; voor de app zie `in_achtergrond`."""
    import shutil

    doel = modelmap() / MODEL
    if doel.is_file() and doel.stat().st_size == GROOTTE:
        return doel
    modelmap().mkdir(parents=True, exist_ok=True)
    vrij = shutil.disk_usage(modelmap()).free
    if vrij < RUIMTE_NODIG:
        raise RuntimeError(
            f"Te weinig ruimte: er is {vrij / 1e9:.1f} GB vrij, het spraakmodel "
            f"heeft {RUIMTE_NODIG / 1e9:.1f} GB nodig."
        )

    def meld(stap: str, gedaan: int, totaal: int, tekst: str) -> None:
        if melder is not None:
            melder(stap, gedaan, totaal, tekst)

    return _download(URL, doel, melder=meld, stap="model", tekst="Spraakmodel ophalen",
                     sha256=SHA256, verwacht=GROOTTE, stop=stop_event)


def in_achtergrond(melder=None) -> bool:
    """Start het ophalen in een draad. `False` als er al een loopt.

    `melder(soort, data)` krijgt `voortgang` (met `gedaan`/`totaal`), `klaar`
    of `fout`, met `werk: "spraakinstall"` — zoals `muziekinstall`.
    """
    global _draad
    with _slot:
        if is_bezig():
            return False
        _stop.clear()

        def meld(soort: str, data: dict) -> None:
            if melder is not None:
                melder(soort, {"werk": "spraakinstall", **data})

        def werk() -> None:
            try:
                installeer(
                    melder=lambda stap, gedaan, totaal, tekst: meld(
                        "voortgang",
                        {"stap": stap, "gedaan": gedaan, "totaal": totaal, "tekst": tekst},
                    ),
                    stop_event=_stop,
                )
            except Gestopt:
                meld("fout", {"fout": "Gestopt.", "gestopt": True})
                return
            except Exception as e:  # noqa: BLE001 — de gebruiker moet het horen, niet de log
                meld("fout", {"fout": f"Het spraakmodel ophalen lukte niet: {e}"})
                return
            meld("klaar", status())

        _draad = threading.Thread(target=werk, name="spraakinstall", daemon=True)
        _draad.start()
        return True


def stop_installatie() -> bool:
    if not is_bezig():
        return False
    _stop.set()
    return True
