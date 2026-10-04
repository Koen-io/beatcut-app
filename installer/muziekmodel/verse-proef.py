"""De installatie van het muziekmodel van voor naar achter op een lege machine.

`tests/test_muziekinstall.py` toetst hervatten, annuleren, te weinig ruimte en
een beschadigd archief — maar met een nep-HTTP-server, zonder één echte byte.
Dat is met opzet: 11 GB hoort niet in een testsuite. Gevolg was wel dat
"installeren werkt" een bewering was over drie van de vier stappen; de echte
download van 9,4 GB was nooit gedraaid, en annuleren halverwege die download
ook niet.

Dit script doet dat wél. Het haalt echt 11 GB op en duurt dus geld en tijd —
het hoort niet in `release.sh` en niet in CI. Draai het met de hand als er aan
`muziekinstall.py` of aan `paths.muziekmodel()` iets verandert.

    mkdir -p /tmp/verse/wortel/vendor /tmp/verse/steun
    cd ~/Code/projecten/claude-video-editor
    for d in studio styles brands looks skills; do ln -sfn "$PWD/$d" /tmp/verse/wortel/$d; done
    CVE_ROOT=/tmp/verse/wortel BEATCUT_STEUN=/tmp/verse/steun \
      CVE_PROJECTEN=/tmp/verse/projecten PROEF_LOG=/tmp/verse/proef.log \
      .venv/bin/python installer/muziekmodel/verse-proef.py

**`BEATCUT_MUZIEKMODEL` leegzetten is niet genoeg.** `paths.muziekmodel()` zet
`steun_map()/muziekmodel` en `VENDOR/ace-step` áltijd achter de eigen aanwijzing
in de rij, dus op deze machine vindt hij `vendor/ace-step` alsnog en meldt
`installeer()` meteen "al aanwezig". Daarom `CVE_ROOT` naar een wortel met een
lege `vendor/`: dat is de enige manier om zonder de echte map weg te halen een
machine-zonder-model na te doen.

Vier fasen, en de laatste twee zijn de reden dat dit script bestaat:

1. Verse installatie, en halverwege de gewichten-download op Annuleren.
2. Opnieuw starten en doorlopen tot `paths.muziekmodel()` hem vindt.
3. Eén echte track maken — "gevonden" is niet hetzelfde als "bruikbaar".
4. Meet of de balk vóór loopt op wat er echt binnen is. Dat doet hij: de
   Xet-overdracht van Hugging Face zet elk bestand meteen op zijn eindmaat neer
   en vult het daarna, dus `st_size` is de maat die het *gaat* worden.

Uitslag van 04-10-2026 staat in `historie/2026-10-04-verse-installatie-muziekmodel.log`.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from cve import muziekgen, muziekinstall, paths

LOG = open(os.environ.get("PROEF_LOG", "verse-proef.log"), "a", buffering=1, encoding="utf-8")
T0 = time.monotonic()

#: Hoeveel gewichten er binnen moeten zijn voordat fase 1 annuleert. Ruim boven
#: nul, zodat het echt halverwege een lopende download valt en niet ervoor.
ANNULEER_BIJ = 1_500_000_000


def log(tekst: str) -> None:
    LOG.write(f"{time.strftime('%H:%M:%S')}  +{time.monotonic() - T0:7.1f}s  {tekst}\n")


def maat(*mappen: Path) -> str:
    return f"{muziekinstall._mapgrootte(*mappen) / 1e9:.2f} GB"


class Loop:
    """Vangt dezelfde gebeurtenissen op als de app, en logt de balk."""

    def __init__(self, annuleer_bij: int | None = None):
        self.annuleer_bij = annuleer_bij
        self.einde = threading.Event()
        self.uitkomst: tuple[str, dict] | None = None
        self.geannuleerd = False
        self.stap: str | None = None
        self.pct_reeks: list[int] = []
        self.max_gewichten = 0
        self._laatst = 0.0

    def melder(self, naam: str, data: dict) -> None:
        if naam != "voortgang":
            log(f"GEBEURTENIS {naam}: {data}")
            self.uitkomst = (naam, data)
            self.einde.set()
            return

        stap, gedaan, totaal = data["stap"], data["gedaan"], data["totaal"]
        self.pct_reeks.append(data["percentage"])
        nieuw = stap != self.stap
        self.stap = stap
        nu = time.monotonic()
        if nieuw or nu - self._laatst > 15:
            self._laatst = nu
            log(f"  balk {data['percentage']:3d}%  {stap:9s} "
                f"{gedaan / 1e9:6.3f}/{totaal / 1e9:6.3f} GB  {data['tekst']}")

        if stap == "gewichten":
            self.max_gewichten = max(self.max_gewichten, gedaan)
            if self.annuleer_bij and gedaan >= self.annuleer_bij and not self.geannuleerd:
                self.geannuleerd = True
                log(f"  >>> ANNULEREN bij {gedaan / 1e9:.2f} GB gewichten")
                log(f"  >>> stop_installatie() gaf {muziekinstall.stop_installatie()!r}")


def draai(naam: str, annuleer_bij: int | None = None) -> Loop:
    log("")
    log(f"===== {naam} =====")
    lus = Loop(annuleer_bij)
    if not muziekinstall.in_achtergrond(melder=lus.melder):
        raise SystemExit("Er liep al een installatie.")
    while not lus.einde.wait(300):
        log(f"  (nog bezig in stap {lus.stap}, vijf minuten geen afronding)")
    return lus


def op_schijf(*mappen: Path) -> tuple[int, int, int]:
    """(st_size, echte blokken, aantal sparse bestanden) — de kern van fase 4."""
    size = blokken = sparse = 0
    for d in mappen:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            try:
                st = p.stat(follow_symlinks=False)
            except OSError:
                continue
            if not os.path.isfile(p) or p.is_symlink():
                continue
            size += st.st_size
            blokken += st.st_blocks * 512
            if st.st_size > 1_000_000 and st.st_blocks * 512 < st.st_size * 0.9:
                sparse += 1
    return size, blokken, sparse


def fase_1_en_2(doel: Path) -> None:
    een = draai("FASE 1 — verse installatie, annuleren tijdens de gewichten", ANNULEER_BIJ)
    soort = (een.uitkomst or ("", {}))[1].get("soort")
    log(f"  uitkomst fase 1: {een.uitkomst[0]} / soort={soort}")
    log(f"  gewichten geteld op moment van annuleren: {een.max_gewichten / 1e9:.2f} GB")
    log(f"  paths.muziekmodel() na annuleren = {paths.muziekmodel()}")
    log(f"  gereed-marker aanwezig = {(doel / paths.MUZIEKMODEL_GEREED).is_file()}")
    log(f"  op schijf: venv {maat(doel / '.venv')}, "
        f"checkpoints+hf {maat(doel / 'checkpoints', doel / 'hf')}")
    log(f"  balk fase 1: {min(een.pct_reeks)}% -> {max(een.pct_reeks)}%")
    if een.uitkomst[0] != "fout" or soort != "Gestopt":
        raise SystemExit("FASE 1 MISLUKT: annuleren leverde geen Gestopt op")
    if paths.muziekmodel() is not None:
        raise SystemExit("FASE 1 MISLUKT: een halve installatie telt als gevonden model")

    half = muziekinstall._mapgrootte(doel / "checkpoints", doel / "hf")
    time.sleep(5)

    twee = draai("FASE 2 — hervatten tot het eind")
    log(f"  uitkomst fase 2: {twee.uitkomst[0]} / {twee.uitkomst[1]}")
    log(f"  balk fase 2: {min(twee.pct_reeks)}% -> {max(twee.pct_reeks)}%")
    log(f"  paths.muziekmodel() = {paths.muziekmodel()}")
    log(f"  gereed-marker aanwezig = {(doel / paths.MUZIEKMODEL_GEREED).is_file()}")
    log(f"  gewichten vóór hervatten {half / 1e9:.2f} GB, "
        f"na afloop {maat(doel / 'checkpoints', doel / 'hf')}")
    log(f"  hele installatie: {maat(doel)}")
    if twee.uitkomst[0] != "klaar":
        raise SystemExit("FASE 2 MISLUKT: geen 'klaar'")
    if paths.muziekmodel() != doel:
        raise SystemExit(f"FASE 2 MISLUKT: muziekmodel() = {paths.muziekmodel()}")


def fase_3() -> None:
    log("")
    log("===== FASE 3 — is de verse installatie bruikbaar? =====")
    st = muziekgen.status()
    log(f"  status(): aanwezig={st['aanwezig']} pad={st['pad']} "
        f"bytes={st['bytes'] / 1e9:.2f} GB genres={len(st['genres'])}")
    if not st["aanwezig"] or st["pad"] != str(paths.steun_map() / "muziekmodel"):
        raise SystemExit("FASE 3 MISLUKT: status() wijst niet naar de verse installatie")

    laatst = [0.0]

    def melder(gedaan: int, totaal: int, tekst: str) -> None:
        nu = time.monotonic()
        if nu - laatst[0] > 20:
            laatst[0] = nu
            log(f"  {gedaan}/{totaal}  {tekst}")

    varianten = muziekgen.genereer(
        "verse-installatie-proef", genre="House", bpm=124, duur=10.0,
        varianten=1, seed=20261004, melder=melder,
    )
    for v in varianten:
        p = Path(v["pad"])
        log(f"  variant: duur={v['duur']}s maten={v['maten']} "
            f"bpm_gemeten={v['bpm_gemeten']} seed={v['seed']}")
        log(f"  bestand bestaat={p.exists()} grootte={p.stat().st_size / 1e6:.2f} MB")
        if not p.exists() or p.stat().st_size < 100_000:
            raise SystemExit("FASE 3 MISLUKT: geen bruikbaar wav-bestand")
    muziekgen.stop_server()


def fase_4(doel: Path) -> None:
    """De gewichten nog één keer ophalen, en de balk naast de schijf leggen."""
    log("")
    log("===== FASE 4 — loopt de balk voor op de schijf? =====")
    opzij = doel.parent / "checkpoints.bewaard"
    (doel / "checkpoints").rename(opzij)
    (doel / paths.MUZIEKMODEL_GEREED).unlink(missing_ok=True)
    log(f"  gewichten opzij in {opzij}; paths.muziekmodel() = {paths.muziekmodel()}")

    stop = threading.Event()

    def kijker() -> None:
        while not stop.wait(1.0):
            size, blokken, sparse = op_schijf(doel / "checkpoints", doel / "hf")
            log(f"  meting  balk-telling {size / 1e9:6.3f} GB | echt op schijf "
                f"{blokken / 1e9:6.3f} GB | sparse bestanden {sparse}")

    threading.Thread(target=kijker, daemon=True).start()
    vier = draai("FASE 4 — download, met de meter ernaast")
    stop.set()
    time.sleep(1.5)
    size, blokken, _ = op_schijf(doel / "checkpoints", doel / "hf")
    log(f"  na afloop: balk-telling {size / 1e9:.3f} GB, echt {blokken / 1e9:.3f} GB")
    if vier.uitkomst[0] != "klaar":
        raise SystemExit("FASE 4 MISLUKT: geen 'klaar'")


def main() -> None:
    doel = muziekinstall.doelmap()
    log("#" * 72)
    log(f"ROOT   = {paths.ROOT}")
    log(f"VENDOR = {paths.VENDOR} (ace-step aanwezig: {(paths.VENDOR / 'ace-step').exists()})")
    log(f"steun  = {paths.steun_map()}")
    log(f"paths.muziekmodel() vooraf = {paths.muziekmodel()}")
    log(f"vrije ruimte = {muziekinstall.ruimte_vrij() / 1e9:.1f} GB")
    if paths.muziekmodel() is not None:
        raise SystemExit(
            "Er staat al een model in zicht — dan toetst dit script niets. "
            "Zet CVE_ROOT naar een wortel met een lege vendor/."
        )

    fase_1_en_2(doel)
    fase_3()
    fase_4(doel)
    log("")
    log("ALLES GROEN: verse installatie, annuleren, hervatten en één echte track.")


if __name__ == "__main__":
    main()
