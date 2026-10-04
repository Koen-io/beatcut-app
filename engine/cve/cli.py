"""Commandoregel-ingang van de engine.

    cve doctor          controleer de installatie
    cve versie          toon versie
"""

from __future__ import annotations

import typer

from . import __version__
from .doctor import rapport

app = typer.Typer(help="BeatCut Video Editor - engine", no_args_is_help=True)


@app.command()
def doctor() -> None:
    """Controleer of alle onderdelen aanwezig en werkend zijn."""
    raise typer.Exit(code=rapport())


@app.command()
def ingest(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    overschrijf: bool = typer.Option(False, "--overschrijf", help="Bestaande proxies opnieuw maken"),
    workers: int = typer.Option(4, "--workers", help="Aantal parallelle proxy-taken"),
) -> None:
    """Lees bronnen in, lees metadata, maak proxies."""
    from .ingest import ingest as _ingest, samenvatting

    data = _ingest(project, overschrijf=overschrijf, workers=workers)
    typer.echo("")
    typer.echo(samenvatting(data))


@app.command()
def analyse(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    workers: int = typer.Option(6, "--workers", help="Aantal parallelle processen"),
    geen_audio: bool = typer.Option(False, "--geen-audio", help="Sla audio per clip over"),
    stijl: str = typer.Option("actie", "--stijl", help="Naam van het bestand in styles/"),
) -> None:
    """Analyseer beeld, audio, telemetrie en muziek. Schrijft analysis.json."""
    from .analyse import analyseer, samenvatting

    data = analyseer(project, workers=workers, met_clip_audio=not geen_audio, stijl=stijl)
    typer.echo("")
    typer.echo(samenvatting(data))


@app.command()
def regie(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    duur: float = typer.Option(None, "--duur", help="Doelduur in seconden"),
    vorm: str = typer.Option("16:9", "--vorm", help="16:9, 9:16 of 1:1"),
    stijl: str = typer.Option("actie", "--stijl"),
    merk: str = typer.Option("prive", "--merk"),
    muziek_start: float = typer.Option(0.0, "--muziek-start", help="Vanaf welke seconde in de track"),
    brief: str = typer.Option("", "--brief", help="Wat je wilt, in gewone taal"),
    regisseur: str = typer.Option("preset", "--regisseur", help="preset | lokaal | claude"),
) -> None:
    """Maak een montagevoorstel. Schrijft edl.json."""
    import json

    from .director import Brief as _Brief
    from .director import kies_regisseur
    from . import paths as _paths

    pdir = _paths.project_dir(project)
    analyse_pad = pdir / "analysis.json"
    if not analyse_pad.exists():
        typer.echo(f"Geen analysis.json. Draai eerst: cve analyse {project}")
        raise typer.Exit(1)

    analyse = json.loads(analyse_pad.read_text(encoding="utf-8"))
    r = kies_regisseur(regisseur)
    voorstel = r.stel_voor(
        analyse,
        _Brief(
            tekst=brief,
            doelduur=duur,
            stijl=stijl,
            merk=merk,
            vorm=vorm,
            muziek_start=muziek_start,
        ),
    )
    pad = voorstel.edl.schrijf(pdir / "edl.json")
    typer.echo("")
    typer.echo(voorstel.edl.samenvatting())
    typer.echo("")
    typer.echo(voorstel.uitleg)
    for w in voorstel.waarschuwingen:
        typer.echo(f"let op: {w}")
    typer.echo(f"\nGeschreven: {pad}")


@app.command()
def render(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    eind: bool = typer.Option(False, "--eind", help="Render uit de bronbestanden op volle kwaliteit"),
    workers: int = typer.Option(4, "--workers"),
) -> None:
    """Render edl.json naar een MP4."""
    from .render import RenderOpties, render as _render

    _render(project, opties=RenderOpties(modus="eind" if eind else "preview", workers=workers))


@app.command()
def review(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    bestand: str = typer.Option("", "--bestand", help="Welke render; standaard de nieuwste"),
    json_uit: bool = typer.Option(False, "--json", help="Alleen het rapport als JSON"),
) -> None:
    """Kijk de render mechanisch na: frames, zwart, stilstand, beat, geluid."""
    import json as _json
    from pathlib import Path as _Path

    from .review import review as _review

    rap = _review(
        project,
        bestand=_Path(bestand) if bestand else None,
        log=(lambda *_: None) if json_uit else typer.echo,
    )
    if json_uit:
        typer.echo(_json.dumps(rap.naar_dict(), indent=1, ensure_ascii=False))
    else:
        typer.echo("")
        typer.echo(rap.tekst())
    raise typer.Exit(code=0 if rap.geslaagd else 1)


@app.command()
def maak(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
    duur: float = typer.Option(None, "--duur", help="Doelduur in seconden"),
    vorm: str = typer.Option("16:9", "--vorm"),
    stijl: str = typer.Option("actie", "--stijl"),
    eind: bool = typer.Option(False, "--eind", help="Ook meteen op volle kwaliteit renderen"),
) -> None:
    """De hele pijplijn in een keer: ingest, analyse, regie, render."""
    import json

    from . import paths as _paths
    from .analyse import analyseer
    from .director import Brief as _Brief
    from .director import kies_regisseur
    from .ingest import ingest as _ingest
    from .render import RenderOpties, render as _render

    pdir = _paths.project_dir(project)

    if not (pdir / "ingest.json").exists():
        typer.echo("[1/4] ingest")
        _ingest(project)
    else:
        typer.echo("[1/4] ingest  (overgeslagen, ingest.json bestaat al)")

    if not (pdir / "analysis.json").exists():
        typer.echo("[2/4] analyse")
        analyseer(project, stijl=stijl)
    else:
        typer.echo("[2/4] analyse (overgeslagen, analysis.json bestaat al)")

    typer.echo("[3/4] regie")
    analyse = json.loads((pdir / "analysis.json").read_text(encoding="utf-8"))
    voorstel = kies_regisseur("preset").stel_voor(
        analyse, _Brief(doelduur=duur, stijl=stijl, vorm=vorm)
    )
    voorstel.edl.schrijf(pdir / "edl.json")
    typer.echo("      " + voorstel.uitleg)

    typer.echo("[4/5] render")
    uit = _render(project, opties=RenderOpties(modus="eind" if eind else "preview"))

    # Nakijken hoort bij maken. Een montage die je zelf niet gecontroleerd hebt
    # afleveren is precies wat fase 7 moest afschaffen.
    typer.echo("\n[5/5] nakijken")
    from .review import review as _review

    rap = _review(project, bestand=uit, log=lambda *_: None)
    typer.echo(rap.tekst())


@app.command()
def studio(
    project: str = typer.Argument("", help="Projectmap; leeg opent het startscherm"),
    poort: int = typer.Option(8420, "--poort"),
    geen_browser: bool = typer.Option(False, "--geen-browser"),
) -> None:
    """Open de video-editor in de browser. Zonder project: het startscherm."""
    from .studio import start

    start(project, poort=poort, open_browser=not geen_browser)


@app.command()
def ondertitels(
    project: str = typer.Argument(..., help="Naam van de projectmap onder projecten/"),
) -> None:
    """Maak ondertitels uit de montage met whisper.cpp (lokaal)."""
    from .transcript import maak

    data = maak(project)
    for r in data["regels"][:12]:
        typer.echo(f"  {r['start']:6.2f}s  {r['tekst']}")
    if len(data["regels"]) > 12:
        typer.echo(f"  ... en nog {len(data['regels']) - 12} regels")


@app.command()
def stijl(
    naam: str = typer.Argument(..., help="Naam van het bestand in styles/"),
    vergeet: bool = typer.Option(False, "--vergeet", help="Gooi het geleerde weg"),
    opnieuw: bool = typer.Option(False, "--leer", help="Herbereken uit alle keuzes"),
) -> None:
    """Toon wat een stijl weegt, en wat er uit jouw keuzes geleerd is."""
    from . import geheugen, paths as _paths
    from .stijl import laad

    if vergeet:
        weg = geheugen.vergeet(naam)
        typer.echo("Het geleerde is gewist." if weg else "Er was nog niets geleerd.")
        return
    if opnieuw:
        geheugen.leer(naam)

    st = laad(naam, _paths.STYLES)
    g = geheugen.laad_geleerd(naam)
    bewijs = g.get("bewijs", {})

    typer.echo(f"\n{st.titel}  ·  {naam}")
    typer.echo(st.omschrijving)
    typer.echo(f"\n{'signaal':16}{'stijlbestand':>13}{'geleerd':>10}{'effectief':>11}   waarnemingen")
    for signaal, basis in st.basis.signalen().items():
        d = st.bijstelling.get(signaal, 0.0)
        n = bewijs.get(signaal, 0)
        pijl = "" if abs(d) < 1e-9 else ("  omhoog" if d > 0 else "  omlaag")
        typer.echo(
            f"{signaal:16}{basis:>13.2f}{d:>+10.3f}{getattr(st.gewichten, signaal):>11.2f}"
            f"   {n:>3}{pijl}"
        )

    aantal = g.get("keuzes", 0)
    typer.echo(
        f"\n{aantal} keuze(s) vastgelegd voor deze stijl. "
        f"Vanaf {geheugen.MIN_KEUZES} waarnemingen per signaal telt het mee, "
        f"met hoogstens {geheugen.MAX_BIJSTELLING:.2f} bijstelling."
    )
    if not aantal:
        typer.echo(
            "Nog niets geleerd. Vervang, verwijder of zet shots vast in de Studio; "
            "elke keuze telt vanzelf mee."
        )


@app.command()
def geo(
    installeer: bool = typer.Option(False, "--installeer", help="Haal de plaatsenlijst op"),
    lijst: str = typer.Option("cities15000", "--lijst", help="cities15000 | cities5000 | cities1000"),
    proef: str = typer.Option("", "--proef", help="Zoek een plaats bij 'lat,lon'"),
) -> None:
    """Plaatsnamen bij coördinaten. Eén keer ophalen, daarna offline."""
    from . import geo as _geo

    if installeer:
        _geo.installeer(lijst, log=typer.echo)
        return

    if proef:
        try:
            lat, lon = (float(x) for x in proef.split(",", 1))
        except ValueError:
            typer.echo("Geef het op als: --proef 47.5007,11.0995")
            raise typer.Exit(1)
        p = _geo.dichtstbij(lat, lon)
        typer.echo(f"{p.naam} ({p.land}) · {p.afstand_km:.1f} km" if p else "Geen plaats gevonden.")
        return

    if _geo.is_geinstalleerd():
        n = len(_geo._laad())
        typer.echo(f"{n} plaatsen beschikbaar in {_geo.gegevens_pad()}")
    else:
        typer.echo(
            "Nog geen plaatsenlijst. Haal hem op met:\n"
            "  cve geo --installeer\n\n"
            "Dat is eenmalig ongeveer 1,5 MB van geonames.org. Daarna werken "
            "plaatsnamen zonder internet."
        )


@app.command()
def rpc() -> None:
    """Draai als sidecar van de app: JSON-RPC over stdin/stdout."""
    from .rpc import draai

    draai()


@app.command()
def versie() -> None:
    """Toon de versie van de engine."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
