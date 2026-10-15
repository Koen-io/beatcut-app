"""Een project verwijderen: meten, eerst een kopie, en dan naar de prullenbak.

Drie dingen staan hier vast, en ze zijn alle drie een belofte aan de gebruiker:

- **De originelen raakt dit nooit aan.** Alles wat hier weg kan staat ín de
  projectmap. Wat de gebruiker ooit importeerde is daar een kopie van; het
  bestand op zijn camera, telefoon of schijf ligt buiten bereik van deze code.
- **Niets gaat hard weg.** De projectmap gaat als één ding naar de prullenbak
  van het besturingssysteem. Kan dat niet (een netwerkschijf zonder
  prullenbak), dan is dat een foutmelding en geen stille `rmtree`.
- **Eerst bewaren, dan pas weghalen.** De kopie wordt geschreven én nagelezen
  voordat er één bestand verplaatst wordt. Mislukt de kopie, dan is er niets
  gebeurd.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import __version__, editie, media, paths, projecten

# Wat de gebruiker kan kiezen te houden. Al het andere in de projectmap is
# `werk`: proxies, analyse, cache, montage. Dat ís het project en gaat altijd.
KEUZES: dict[str, str] = {"kopieen": "bronnen", "muziek": "muziek", "exports": "renders"}
SOORTEN = ("werk", *KEUZES)

# Hier komt terecht wat de gebruiker wilde houden. De underscore is de
# afspraak: `projecten.veilige_naam()` maakt van elke underscore een streepje,
# dus een project kan nooit zo heten, en `projecten.alle()` slaat de map over.
BEWAARD = "_Bewaard"

MANIFEST = "beatcut-kopie.json"
_KOPIE_SOORT = "beatcut-projectkopie"
_KOPIE_VERSIE = 1


def _naar_prullenbak(pad: Path) -> None:
    """Eén deur naar de prullenbak, zodat een test hem kan omleiden."""
    from send2trash import send2trash

    send2trash(str(pad))


def prullenbak_naam() -> str:
    return "Prullenbak" if sys.platform == "win32" else "Prullenmand"


def projectmap(naam: str) -> Path:
    """De projectmap, of een fout. Nooit iets buiten `PROJECTEN`."""
    p = paths.PROJECTEN / naam
    if (
        not naam
        or naam.startswith((".", "_"))
        or Path(naam).name != naam
        or p.parent != paths.PROJECTEN
        or p.is_symlink()
        or not p.is_dir()
    ):
        raise ValueError(f"Project '{naam}' bestaat niet.")
    return p


def _meet(pad: Path) -> tuple[int, int]:
    """(bytes, bestanden) onder `pad`. Volgt geen koppelingen: wat buiten de
    projectmap ligt telt niet mee en komt er ook niet door vrij."""
    if pad.is_symlink() or not pad.exists():
        return 0, 0
    if pad.is_file():
        return pad.stat().st_size, 1
    grootte = aantal = 0
    for q in pad.rglob("*"):
        if q.is_file() and not q.is_symlink():
            grootte += q.stat().st_size
            aantal += 1
    return grootte, aantal


def _loopt(naam: str) -> str | None:
    """Wat er nu voor dit project draait, of None."""
    from . import muziekgen

    tekst = projecten.is_bezig(naam)
    if tekst:
        return tekst
    return "Muziek componeren…" if muziekgen.is_bezig(naam) else None


def _kopie_inhoud(p: Path, *, proxies: bool) -> list[Path]:
    """Wat er in de kopie gaat: de montage, de analyse, de keuzes en de muziek.

    De geïmporteerde video's gaan niet mee — die zijn groot en de gebruiker
    heeft de originelen. Het manifest noemt ze bij naam, zodat je bij het
    terugzetten weet welke je er weer bij moet slepen.
    """
    uit = [q for q in sorted(p.iterdir()) if q.is_file() and not q.name.startswith(".")]
    # De hele muziekmap, ook wat eronder ligt: gegenereerde nummers staan met
    # hun gegevens in `muziek/gegenereerd/`, en alleen het gekozen nummer
    # staat er ook boven. "Muziek" in de dialoog is alles wat hier ligt.
    if (p / "muziek").is_dir():
        uit += [
            q for q in sorted((p / "muziek").rglob("*"))
            if q.is_file() and not any(d.startswith(".") for d in q.relative_to(p).parts)
        ]
    if proxies and (p / "proxies").is_dir():
        uit += [q for q in sorted((p / "proxies").rglob("*")) if q.is_file()]
    return [q for q in uit if not q.is_symlink()]


def omvang(naam: str) -> dict:
    """Hoeveel ruimte het project inneemt, per soort — gemeten, niet geschat."""
    p = projectmap(naam)
    soorten = {s: {"bytes": 0, "bestanden": 0} for s in SOORTEN}
    mappen = {m: s for s, m in KEUZES.items()}
    for kind in p.iterdir():
        grootte, aantal = _meet(kind)
        soort = soorten[mappen.get(kind.name, "werk")]
        soort["bytes"] += grootte
        soort["bestanden"] += aantal
    proxies = _meet(p / "proxies")[0]
    basis = sum(q.stat().st_size for q in _kopie_inhoud(p, proxies=False))
    return {
        "naam": naam,
        "aantal_clips": len(media.vind_bronnen(p / "bronnen")),
        "soorten": soorten,
        "totaal": sum(s["bytes"] for s in soorten.values()),
        "kopie": {"basis": basis, "proxies": proxies},
        "bezig": _loopt(naam),
        "prullenbak": prullenbak_naam(),
        "bewaard": str(paths.PROJECTEN / BEWAARD / naam),
    }


def maak_kopie(naam: str, doel: str | Path, *, proxies: bool = False) -> Path:
    """Schrijf het project als één `.zip` naar `doel`, en lees hem na."""
    p = projectmap(naam)
    doel = Path(doel).expanduser()
    if doel.suffix.lower() != ".zip":
        doel = doel.with_name(doel.name + ".zip")
    if p.resolve() in doel.resolve().parents:
        raise ValueError("Bewaar de kopie buiten de projectmap — die gaat zo weg.")
    vandaan = projecten.herkomst(naam)
    manifest = {
        "soort": _KOPIE_SOORT,
        "versie": _KOPIE_VERSIE,
        "project": naam,
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "beatcut": __version__,
        "proxies": proxies,
        # `pad`: waar het origineel stond bij het importeren. Daar kijkt
        # terugzetten als eerste; onbekend (een ouder project) is None.
        "bronnen": [
            {"naam": b.name, "bytes": b.stat().st_size, "pad": vandaan.get(b.name)}
            for b in media.vind_bronnen(p / "bronnen")
        ],
    }
    # Eerst onder een andere naam: een half geschreven zip mag nooit de naam
    # dragen die de gebruiker koos, en al helemaal niet als "de kopie" tellen.
    deel = doel.with_name(doel.name + ".deel")
    try:
        with zipfile.ZipFile(deel, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for q in _kopie_inhoud(p, proxies=proxies):
                # Video en audio zijn al gecomprimeerd; nog eens persen kost
                # alleen tijd.
                plat = q.suffix.lower() == ".json"
                z.write(
                    q, q.relative_to(p).as_posix(),
                    compress_type=zipfile.ZIP_DEFLATED if plat else zipfile.ZIP_STORED,
                )
        with zipfile.ZipFile(deel) as z:
            kapot = z.testzip()
        if kapot is not None:
            raise OSError(f"De kopie is niet goed weggeschreven ({kapot}).")
        deel.replace(doel)
    except BaseException:
        deel.unlink(missing_ok=True)
        raise
    return doel


def _open_kopie(zip_pad: str | Path) -> tuple[zipfile.ZipFile, dict]:
    """De zip en zijn manifest, of een fout die zegt wat er mis is.

    Dit bestand komt van buiten — de gebruiker wees het aan. Alles wat erin
    staat is dus invoer, geen waarheid.
    """
    pad = Path(zip_pad).expanduser()
    if not pad.is_file():
        raise ValueError(f"'{pad.name}' is er niet (meer). Kies het bestand opnieuw.")
    try:
        z = zipfile.ZipFile(pad)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(
            f"'{pad.name}' is geen .zip-bestand, of het is beschadigd. "
            f"Kies de kopie die {editie.NAAM} bij het verwijderen maakte."
        ) from e
    try:
        try:
            manifest = json.loads(z.read(MANIFEST))
        except (KeyError, ValueError, zipfile.BadZipFile, zlib.error) as e:
            raise ValueError(f"Dit is geen kopie van een {editie.NAAM}-project.") from e
        if not isinstance(manifest, dict) or manifest.get("soort") != _KOPIE_SOORT:
            raise ValueError(f"Dit is geen kopie van een {editie.NAAM}-project.")
        versie = manifest.get("versie")
        if isinstance(versie, int) and versie > _KOPIE_VERSIE:
            raise ValueError(
                f"Deze kopie is gemaakt met een nieuwere {editie.NAAM} ({manifest.get('beatcut', '?')}). "
                f"Werk {editie.NAAM} bij en zet hem daarna terug."
            )
    except BaseException:
        z.close()
        raise
    return z, manifest


def _inhoud(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [lid for lid in z.infolist() if not lid.is_dir() and lid.filename != MANIFEST]


def _vrije_naam(basis: str) -> str:
    vrij, n = basis, 2
    while (paths.PROJECTEN / vrij).exists():
        vrij, n = f"{basis}-{n}", n + 1
    return vrij


def _grootte(pad: Path) -> int:
    """De grootte van een bestand, of -1 als het er niet is. Een pad van een
    andere computer (`D:\\Video\\…` op een Mac) is er gewoon niet."""
    try:
        return pad.stat().st_size if pad.is_file() else -1
    except (OSError, ValueError):
        return -1


def _zoek_bronnen(manifest: dict, zoek: list[str] | None) -> list[dict]:
    """Per video uit de kopie: waar hij nu te vinden is (`pad`), of None.

    Eerst op de plek waar hij bij het importeren stond (`oud`) — dat pad is
    van precies deze clip. Dan op de plekken die de gebruiker aanwees (`zoek`:
    mappen of losse bestanden). Elk gevonden bestand hoort bij hoogstens één
    clip: twee kaartjes kunnen elk een `IMG_0001.MOV` van dezelfde grootte
    hebben, en dan is één keer hetzelfde beeld twee keer gebruiken erger dan
    een clip die ontbreekt.
    Hetzelfde bestand is: dezelfde naam én dezelfde grootte. Alleen de naam is
    te weinig — elke camera maakt een `IMG_0001.MOV`, en een montage met de
    verkeerde beelden eronder is erger dan een clip die ontbreekt.

    ponytail: een aangewezen map wordt helemaal doorlopen. Wijst iemand zijn
    hele thuismap aan, dan duurt dat; een index is pas nodig als dat knelt.
    """
    gevonden: dict[tuple[str, int], list[Path]] = {}
    for ruw in zoek or []:
        plek = Path(ruw).expanduser()
        kandidaten = media.vind_bronnen(plek, diep=True) if plek.is_dir() else [plek]
        for q in kandidaten:
            rij = gevonden.setdefault((q.name.casefold(), _grootte(q)), [])
            if q not in rij:
                rij.append(q)
    uit: list[dict] = []
    gebruikt: set[Path] = set()
    for b in manifest.get("bronnen") or []:
        if not isinstance(b, dict):
            continue
        naam, oud = str(b.get("naam") or ""), b.get("pad")
        # De naam wordt straks een bestand in `bronnen/`. `PureWindowsPath`
        # kent beide soorten schuine streep, op elk systeem.
        if PureWindowsPath(naam).name != naam or Path(naam).suffix.lower() not in media.VIDEO_EXTENSIES:
            continue
        try:
            grootte = int(b.get("bytes"))
        except (TypeError, ValueError):
            continue
        oud = oud if isinstance(oud, str) and oud else None
        # Twee kaartjes met elk een IMG_0001.MOV: de tweede heet in het project
        # IMG_0001-2.MOV, maar op de camera niet. Beide namen tellen.
        namen = [naam.casefold()] + ([PureWindowsPath(oud).name.casefold()] if oud else [])
        uit.append({"naam": naam, "bytes": grootte, "oud": oud, "pad": None, "_namen": namen})

    def neem(b: dict, pad: Path) -> None:
        b["pad"] = str(pad)
        gebruikt.add(pad.resolve())

    for b in uit:
        if b["oud"] and _grootte(Path(b["oud"])) == b["bytes"] and Path(b["oud"]).resolve() not in gebruikt:
            neem(b, Path(b["oud"]))
    for b in uit:
        if b["pad"] is None:
            vrij = (q for n in b["_namen"] for q in gevonden.get((n, b["bytes"]), [])
                    if q.resolve() not in gebruikt)
            hier = next(vrij, None)
            if hier is not None:
                neem(b, hier)
    for b in uit:
        del b["_namen"]
    return uit


def bekijk_kopie(
    zip_pad: str | Path, naam: str | None = None, zoek: list[str] | None = None
) -> dict:
    """Wat er in een kopie zit en wat terugzetten zou doen. Schrijft niets."""
    z, manifest = _open_kopie(zip_pad)
    with z:
        leden = _inhoud(z)
    project = str(manifest.get("project") or "")
    basis = projecten.veilige_naam(naam or project)
    bronnen = _zoek_bronnen(manifest, zoek)
    return {
        "pad": str(zip_pad),
        "project": project,
        # Onder welke naam hij terugkomt. `bezet`: de gevraagde naam is al van
        # een ander project, dus dit is een voorstel ernaast.
        "naam": _vrije_naam(basis),
        "bezet": (paths.PROJECTEN / basis).exists(),
        "gemaakt": manifest.get("gemaakt"),
        "beatcut": manifest.get("beatcut"),
        "aantal_clips": len(bronnen),
        "bronnen": bronnen,
        "proxies": any(lid.filename.startswith("proxies/") for lid in leden),
        "heeft_montage": any(lid.filename == "edl.json" for lid in leden),
        "heeft_muziek": any(lid.filename.startswith("muziek/") for lid in leden),
        "bytes": Path(zip_pad).expanduser().stat().st_size,
        "uitgepakt": sum(lid.file_size for lid in leden),
    }


def zet_terug(
    zip_pad: str | Path, naam: str | None = None, zoek: list[str] | None = None
) -> dict:
    """Maak van een kopie weer een project.

    Bestaat de naam al, dan komt er een volgnummer achter: terugzetten
    overschrijft nooit een project dat er nu staat. De video's die nog te
    vinden zijn (zie `_zoek_bronnen`) worden opnieuw geïmporteerd — een kopie,
    het origineel blijft waar het staat. Gaat er iets mis, dan is er daarna
    geen half project.
    """
    z, manifest = _open_kopie(zip_pad)
    with z:
        leden = _inhoud(z)
        vrij = _vrije_naam(projecten.veilige_naam(naam or str(manifest.get("project") or "")))
        wortel = (paths.PROJECTEN / vrij).resolve()
        # Een zip van buiten mag nergens anders schrijven dan in zijn eigen
        # projectmap, wat er ook in de namen staat. Eerst alles nakijken, dan
        # pas de map maken.
        for lid in leden:
            if wortel not in (wortel / lid.filename).resolve().parents:
                raise ValueError(f"De kopie bevat een onveilig pad: {lid.filename}")
        bronnen = _zoek_bronnen(manifest, zoek)
        p = paths.project_dir(vrij)
        try:
            (p / "muziek").mkdir(exist_ok=True)
            for lid in leden:
                doel = p / lid.filename
                doel.parent.mkdir(parents=True, exist_ok=True)
                with z.open(lid) as bron, doel.open("wb") as uit:
                    shutil.copyfileobj(bron, uit)
            # ponytail: kopiëren blokkeert de engine zolang het duurt, net als
            # importeren. Voortgang erbij als iemand er echt op zit te wachten.
            for b in bronnen:
                if b["pad"]:
                    shutil.copy2(b["pad"], p / "bronnen" / b["naam"])
            projecten.onthoud_herkomst(
                vrij, {b["naam"]: str(Path(b["pad"]).resolve()) for b in bronnen if b["pad"]}
            )
            # Waar het project nog op wacht. Daarmee komt een video die later
            # ingesleept wordt onder zijn eigen naam terug, en blijft de
            # teruggezette analyse staan tot ze er allemaal zijn. Zat er al
            # zo'n lijst in de kopie (een project dat zelf nog wachtte), dan
            # telt die mee; `ontbrekend()` laat weg wat er intussen staat.
            projecten.zet_ontbrekend(vrij, {
                **projecten.ontbrekend(vrij),
                **{b["naam"]: {"bytes": b["bytes"], "oud": b["oud"]} for b in bronnen if not b["pad"]},
            })
            ontbreekt = sorted(projecten.ontbrekend(vrij))
        except BaseException as e:
            # Deze map bestond een tel geleden nog niet en bevat alleen wat
            # hier net is uitgepakt; daarom mag hij hard weg.
            shutil.rmtree(p, ignore_errors=True)
            if isinstance(e, (zipfile.BadZipFile, zlib.error, EOFError)):
                raise ValueError(  # noqa: TRY004 — een kapot bestand, geen verkeerd type
                    "De kopie is beschadigd en kon niet helemaal gelezen worden. "
                    "Er is niets teruggezet."
                ) from e
            if isinstance(e, OSError):
                raise OSError(f"Terugzetten is niet gelukt: {e}. Er is niets teruggezet.") from e
            raise
    gekoppeld = [b["naam"] for b in bronnen if b["pad"]]
    return {
        "naam": vrij,
        "gekoppeld": gekoppeld,
        "ontbreekt": ontbreekt,
        # Alleen met álle video's terug heeft inlezen zin: met een deel zou de
        # ingest opnieuw geschreven worden en past de montage er niet meer op.
        "verwerken": bool(gekoppeld) and not ontbreekt and projecten.moet_inlezen(vrij),
    }


def _vrije_map(basis: Path) -> Path:
    vrij, n = basis, 2
    while vrij.exists():
        vrij, n = basis.with_name(f"{basis.name}-{n}"), n + 1
    return vrij


def verwijder(
    naam: str,
    *,
    weg: list[str] | None = None,
    kopie: str | None = None,
    kopie_proxies: bool = False,
) -> dict:
    """Haal het project weg. `weg` noemt welke keuzesoorten méé weg gaan.

    Wat niet in `weg` staat verhuist naar `_Bewaard/<naam>/`; de rest gaat als
    één map naar de prullenbak. Loopt er werk voor dit project, dan gebeurt er
    niets en volgt een fout.
    """
    p = projectmap(naam)
    weg_set = set(weg if weg is not None else KEUZES)
    onbekend = weg_set - set(KEUZES)
    if onbekend:
        raise ValueError(f"Onbekende soort: {', '.join(sorted(onbekend))}")
    bezig = _loopt(naam)
    # Claimen in dezelfde stap als kijken: anders start er tussen de controle
    # en het verplaatsen alsnog een render in een map die onderweg is.
    if bezig or not projecten.neem_bezig(naam, "Verwijderen…"):
        raise RuntimeError(
            f"'{naam}' is nog bezig ({bezig or 'ander werk'}). Wacht tot dat klaar is."
        )
    try:
        maten = omvang(naam)["soorten"]
        kopie_pad = maak_kopie(naam, kopie, proxies=kopie_proxies) if kopie else None

        bewaard: Path | None = None
        try:
            for soort, mapnaam in KEUZES.items():
                bron = p / mapnaam
                if soort in weg_set or maten[soort]["bestanden"] == 0:
                    continue
                if bewaard is None:
                    bewaard = _vrije_map(paths.PROJECTEN / BEWAARD / naam)
                    bewaard.mkdir(parents=True)
                shutil.move(str(bron), str(bewaard / mapnaam))
            _naar_prullenbak(p)
        except Exception as e:  # noqa: BLE001 — elke oorzaak is dezelfde melding waard
            # Het project staat er nog; dan hoort het ook nog heel te zijn.
            if bewaard is not None:
                for kind in list(bewaard.iterdir()):
                    shutil.move(str(kind), str(p / kind.name))
                bewaard.rmdir()
            raise OSError(
                f"'{naam}' kon niet naar de {prullenbak_naam()}: {e}. "
                "Er is niets definitief verwijderd."
            ) from e
    finally:
        projecten.zet_bezig(naam, None)

    return {
        "naam": naam,
        "vrijgemaakt": maten["werk"]["bytes"] + sum(maten[s]["bytes"] for s in weg_set),
        "bewaard": str(bewaard) if bewaard else None,
        "kopie": str(kopie_pad) if kopie_pad else None,
        "prullenbak": prullenbak_naam(),
    }
