"""Ingang van de ingevroren engine.

PyInstaller heeft één bestand nodig om vanuit te starten. Dat is dit.

Zonder argumenten opent het de Studio - dat is wat er gebeurt als iemand op
het ikoon dubbelklikt. Mét argumenten gedraagt het zich als `cve`, zodat
alles wat op de commandoregel werkt ook in de ingevroren versie werkt:

    beatcut-engine                 de Studio openen
    beatcut-engine review test     precies zoals `cve review test`
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    # Zonder dit start een ingevroren programma zichzelf opnieuw op zodra er
    # een proces bij komt - een venster vol Studio's, en niets werkt.
    multiprocessing.freeze_support()

    from cve.cli import app

    if len(sys.argv) == 1:
        sys.argv.append("studio")
    app()


if __name__ == "__main__":
    main()
