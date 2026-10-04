"""Projectbeheer voor het startscherm.

Een project is een map onder `projecten/` met een vaste indeling. Deze module
weet welke stappen al gedaan zijn, zodat de interface kan tonen waar je bent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import media, paths

# Stappen in volgorde. De interface toont ze als een reeks bolletjes.
STAPPEN = ("beelden", "muziek", "analyse", "montage", "render")


def veilige_naam(naam: str) -> str:
    """Maak van vrije invoer een bruikbare mapnaam."""
    schoon = re.sub(r"[^\w\s-]", "", naam, flags=re.UNICODE).strip()
    schoon = re.sub(r"[\s_]+", "-", schoon).lower()
    return schoon[:60] or "naamloos"


@dataclass
class Status:
    naam: str
    aantal_clips: int = 0
    totaal_duur: float = 0.0
    heeft_muziek: bool = False
    muziek: str | None = None
    is_ingelezen: bool = False
    is_geanalyseerd: bool = False
    heeft_montage: bool = False
    renders: list[str] = field(default_factory=list)
    gewijzigd: str | None = None
    bezig: str | None = None

    @property
    def stap(self) -> str:
        """De eerstvolgende stap die aandacht vraagt."""
        if self.aantal_clips == 0:
            return "beelden"
        if not self.heeft_muziek:
            return "muziek"
        if not self.is_geanalyseerd:
            return "analyse"
        if not self.heeft_montage:
            return "montage"
        return "render"

    @property
    def klaar_om_te_monteren(self) -> bool:
        return self.aantal_clips > 0 and self.is_geanalyseerd


# Lopende achtergrondtaken per project: {"project": "analyse 3/21"}
_bezig: dict[str, str] = {}
_slot = threading.Lock()


def zet_bezig(project: str, tekst: str | None) -> None:
    with _slot:
        if tekst is None:
            _bezig.pop(project, None)
        else:
            _bezig[project] = tekst


def neem_bezig(project: str, tekst: str) -> bool:
    """Claim dit project, maar alleen als er niets loopt.

    Kijken met `is_bezig()` en daarna zetten is twee stappen: twee klikken
    tegelijk komen er dan allebei door en renderen over elkaar heen. Dit is
    één stap onder hetzelfde slot.
    """
    with _slot:
        if _bezig.get(project):
            return False
        _bezig[project] = tekst
        return True


def is_bezig(project: str) -> str | None:
    with _slot:
        return _bezig.get(project)


def alles_bezig() -> dict[str, str]:
    """Alle lopende taken, over alle projecten heen. Een kopie, geen venster."""
    with _slot:
        return dict(_bezig)


def status(naam: str) -> Status:
    p = paths.PROJECTEN / naam
    s = Status(naam=naam, bezig=is_bezig(naam))
    if not p.exists():
        return s

    bronnen = media.vind_bronnen(p / "bronnen")
    muziek = media.vind_muziek(p / "muziek")
    s.aantal_clips = len(bronnen)
    s.heeft_muziek = bool(muziek)
    s.muziek = muziek[0].name if muziek else None

    ingest = p / "ingest.json"
    if ingest.exists():
        try:
            d = json.loads(ingest.read_text(encoding="utf-8"))
            s.is_ingelezen = True
            s.totaal_duur = d.get("totaal_duur", 0.0)
        except (json.JSONDecodeError, OSError):
            pass

    s.is_geanalyseerd = (p / "analysis.json").exists()
    s.heeft_montage = (p / "edl.json").exists()
    s.renders = sorted((r.name for r in (p / "renders").glob("*.mp4")), reverse=True)

    tijden = [q.stat().st_mtime for q in p.glob("*.json")] or [p.stat().st_mtime]
    s.gewijzigd = datetime.fromtimestamp(max(tijden), timezone.utc).isoformat(timespec="seconds")
    return s


def alle() -> list[Status]:
    if not paths.PROJECTEN.exists():
        return []
    namen = sorted(
        (d.name for d in paths.PROJECTEN.iterdir() if d.is_dir() and not d.name.startswith(".")),
    )
    lijst = [status(n) for n in namen]
    lijst.sort(key=lambda s: s.gewijzigd or "", reverse=True)
    return lijst


def maak(naam: str) -> Status:
    veilig = veilige_naam(naam)
    paths.project_dir(veilig)
    (paths.PROJECTEN / veilig / "muziek").mkdir(parents=True, exist_ok=True)
    return status(veilig)


def verwijder(naam: str) -> None:
    p = paths.PROJECTEN / naam
    if p.exists() and p.parent == paths.PROJECTEN:
        shutil.rmtree(p)


def _bestemming(project: str, bestandsnaam: str) -> tuple[Path, str]:
    """Waar dit bestand hoort, op de extensie af. Muziek en video, niets anders."""
    p = paths.project_dir(project)
    (p / "muziek").mkdir(parents=True, exist_ok=True)
    naam = Path(bestandsnaam).name
    ext = Path(naam).suffix.lower()

    if ext in media.AUDIO_EXTENSIES:
        return p / "muziek" / naam, "muziek"
    if ext in media.VIDEO_EXTENSIES:
        return p / "bronnen" / naam, "video"
    raise ValueError(f"Bestandstype {ext or '(onbekend)'} wordt niet ondersteund.")


def bewaar_bestand(project: str, bestandsnaam: str, inhoud: bytes) -> dict:
    """Zet een geupload bestand in de juiste submap op basis van de extensie."""
    doel, soort = _bestemming(project, bestandsnaam)
    doel.write_bytes(inhoud)
    return {"naam": doel.name, "soort": soort, "bytes": len(inhoud)}


RAND = 64 * 1024  # hoeveel we van kop en staart vergelijken


def _rand(pad: Path) -> bytes:
    """Kop en staart van een bestand - genoeg om twee clips te onderscheiden."""
    with pad.open("rb") as f:
        kop = f.read(RAND)
        f.seek(max(0, pad.stat().st_size - RAND))
        return kop + f.read(RAND)


def _zelfde_bestand(a: Path, b: Path) -> bool:
    """Is dit hetzelfde bestand? Grootte, wijzigingsmoment, kop en staart.

    `shutil.copy2` neemt het wijzigingsmoment mee, dus een eerder geïmporteerde
    kopie is hieraan te herkennen zonder 300 MB te hoeven doorrekenen. Hele
    seconden, want niet elk bestandssysteem bewaart meer precisie. De 128 KB
    kop-en-staart erbij, omdat grootte en tijd alleen twee verschillende
    `IMG_0001.MOV` nog voor elkaar kunnen laten doorgaan - en dan was er één weg.
    """
    x, y = a.stat(), b.stat()
    if x.st_size != y.st_size or int(x.st_mtime) != int(y.st_mtime):
        return False
    return _rand(a) == _rand(b)


def _vrije_naam(doel: Path, bron: Path) -> Path | None:
    """Een vrij pad voor deze bron, of None als hij er al staat.

    **Waarom dit moet:** twee kaartjes uit dezelfde camera leveren allebei een
    `IMG_0001.MOV`. Zonder deze controle overschreef de tweede de eerste
    zonder een woord, en kreeg een bestaande montage stilletjes andere beelden.
    """
    if not doel.exists():
        return doel
    if _zelfde_bestand(bron, doel):
        return None
    for n in range(2, 1000):
        kandidaat = doel.with_name(f"{doel.stem}-{n}{doel.suffix}")
        if not kandidaat.exists():
            return kandidaat
        if _zelfde_bestand(bron, kandidaat):
            return None
    raise ValueError(f"te veel bestanden met de naam {doel.name}")


def _uitvouwen(paden: list[str], uit: list[dict]) -> list[Path]:
    """Losse bestanden en gesleepte mappen naar één lijst bestanden.

    Een map in het venster slepen moet net zo goed werken als losse clips —
    dat is de normale manier om een SD-kaart leeg te halen. Wat niet bestaat
    en wat geen videobestand oplevert gaat als fout de lijst in; stil
    overslaan is hoe de gebruiker denkt dat hij 40 clips importeerde.
    """
    uitgevouwen: list[Path] = []
    for ruw in paden:
        bron = Path(ruw).expanduser()
        if bron.is_dir():
            gevonden = media.vind_bronnen(bron, diep=True)
            if not gevonden:
                uit.append({"naam": bron.name, "fout": "geen videobestanden in deze map"})
            uitgevouwen.extend(gevonden)
        elif bron.is_file():
            uitgevouwen.append(bron)
        else:
            uit.append({"naam": bron.name, "fout": "bestand niet gevonden"})
    return uitgevouwen


def voeg_toe(project: str, paden: list[str]) -> list[dict]:
    """Neem bestanden van elders op in het project.

    Een kopie, net als de upload van de oude Studio: het bronbestand blijft
    waar het staat en wordt nooit aangeraakt (regel 4). Twee bronnen met
    dezelfde naam krijgen allebei een plek (`IMG_0001-2.MOV`); een bestand dat
    er al staat wordt overgeslagen.

    ponytail: kopieren kost schijfruimte - 21 clips van 4K60 is zo 6 GB. Een
    hardlink zou gratis zijn op dezelfde schijf, maar wijkt af van wat de
    Studio deed; pas doen als de ruimte echt knelt.
    """
    uit: list[dict] = []
    for bron in _uitvouwen(paden, uit):
        try:
            doel, soort = _bestemming(project, bron.name)
            vrij = _vrije_naam(doel, bron)
        except ValueError as e:
            uit.append({"naam": bron.name, "fout": str(e)})
            continue
        if vrij is None:
            uit.append(
                {"naam": doel.name, "soort": soort, "bytes": doel.stat().st_size,
                 "overgeslagen": "staat al in het project"}
            )
            continue
        shutil.copy2(bron, vrij)
        rij = {"naam": vrij.name, "soort": soort, "bytes": vrij.stat().st_size}
        if vrij.name != bron.name:
            rij["hernoemd_van"] = bron.name
        uit.append(rij)
    return uit


# Clips die de gebruiker uitgezet heeft. De oude Studio hield dit alleen in de
# browser bij en gaf het als URL-parameter door; daardoor was het weg na een
# herlaadactie. De app heeft geen URL's, dus het staat nu op schijf - naast
# `edl.json`, niet erin: deze keuze gaat juist over wat er nog gemonteerd moet
# worden.
SELECTIE = "selectie.json"


def selectie(project: str) -> set[str]:
    """Welke clip-id's staan uit? Lege verzameling als er nog niets gekozen is."""
    pad = paths.PROJECTEN / project / SELECTIE
    try:
        return set(json.loads(pad.read_text(encoding="utf-8"))["uit"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return set()


def zet_selectie(project: str, clip: str, aan: bool) -> set[str]:
    """Zet een clip aan of uit en bewaar dat. Geeft de nieuwe stand terug."""
    uit = selectie(project)
    if aan:
        uit.discard(clip)
    else:
        uit.add(clip)
    pad = paths.project_dir(project) / SELECTIE
    pad.write_text(
        json.dumps({"versie": 1, "uit": sorted(uit)}, indent=1), encoding="utf-8"
    )
    return uit


THUMB_BREEDTE = 320


def _scores(pdir: Path) -> dict[str, float]:
    """Beste segmentscore per clip-id, als de analyse gedraaid is."""
    try:
        a = json.loads((pdir / "analysis.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    best: dict[str, float] = {}
    for s in a.get("segmenten") or []:
        cid = s.get("clip")
        if cid is not None:
            best[cid] = max(best.get(cid, 0.0), float(s.get("score", 0.0)))
    return best


def _thumbnail(pdir: Path, naam: str, beeld: Path, duur: float) -> str | None:
    """Pad naar het kaartbeeldje, aangemaakt als het er nog niet is."""
    doel = pdir / "cache" / "kaart" / f"{Path(naam).stem}.jpg"
    try:
        media.maak_thumbnail(beeld, doel, breedte=THUMB_BREEDTE, op=min(0.3, duur / 4))
    except Exception:  # noqa: BLE001 — één stuk bestand mag de lijst niet slopen
        return None
    return str(doel)


def clips(project: str) -> list[dict]:
    """Alle clips van een project, met beeldje, meting en aan/uit.

    Werkt ook vóór de ingest: dan komen duur en formaat rechtstreeks uit
    ffprobe en staat het beeldje uit het bronbestand in plaats van uit de
    proxy. Zo heeft stap 1 van de app meteen iets te tonen.
    """
    pdir = paths.PROJECTEN / project
    if not pdir.is_dir():
        return []
    uitgezet = selectie(project)
    scores = _scores(pdir)
    ingest_pad = pdir / "ingest.json"

    rijen: list[dict] = []
    if ingest_pad.exists():
        try:
            ing = json.loads(ingest_pad.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            ing = {"clips": []}
        for c in ing.get("clips") or []:
            proxy = pdir / "proxies" / c["proxy"]
            bron = pdir / "bronnen" / c["bestand"]
            rijen.append(
                {
                    "naam": c["bestand"],
                    "id": c["id"],
                    "bron": str(bron),
                    "duur": c["duur"],
                    "breedte": c["breedte"],
                    "hoogte": c["hoogte"],
                    "fps": c["fps"],
                    "score": round(scores[c["id"]], 3) if c["id"] in scores else None,
                    "aan": c["bestand"] not in uitgezet,
                    "thumbnail": _thumbnail(
                        pdir, c["bestand"], proxy if proxy.exists() else bron, c["duur"]
                    ),
                }
            )
        return rijen

    for p in media.vind_bronnen(pdir / "bronnen"):
        try:
            info = media.probe(p)
        except Exception as e:  # noqa: BLE001 — onleesbaar bestand is geen reden tot stilstand
            print(f"clip overgeslagen ({p.name}): {e}", file=sys.stderr)
            continue
        rijen.append(
            {
                "naam": p.name,
                "id": None,
                "bron": str(p),
                "duur": round(info.duur, 3),
                "breedte": info.breedte,
                "hoogte": info.hoogte,
                "fps": round(info.fps, 3),
                "score": None,
                "aan": p.name not in uitgezet,
                "thumbnail": _thumbnail(pdir, p.name, p, info.duur),
            }
        )
    return rijen


def open_map(project: str, welke: str = "bronnen") -> None:
    """Open de projectmap in de bestandsbeheerder van het besturingssysteem."""
    doel = paths.project_dir(project) / welke
    doel.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        cmd = ["open", str(doel)]
    elif sys.platform == "win32":
        cmd = ["explorer", str(doel)]
    else:
        cmd = ["xdg-open", str(doel)]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Ingest en analyse loggen hun vorderingen als "  [3/21] C03". Dat is het enige
# getal dat ze geven, dus daar komt de teller van de voortgangsbalk uit. Liever
# dit dan een tweede voortgangsadministratie in ingest.py en analyse.py.
_TELLER = re.compile(r"\[(\d+)/(\d+)\]")


def moet_inlezen(project: str, *, opnieuw: bool = False) -> bool:
    """Is de ingest er nog niet, of klopt hij niet meer met wat er ligt?

    **Zonder deze controle komen later toegevoegde clips nooit in de analyse.**
    De oude Studio sloeg het inlezen over zodra `ingest.json` bestond; wie
    daarna nog beelden toevoegde, zag ze in de lijst staan en nergens anders.
    Opnieuw inlezen is goedkoop: bestaande proxies blijven staan, alleen de
    nieuwe clips worden omgezet.
    """
    p = paths.PROJECTEN / project
    pad = p / "ingest.json"
    if opnieuw or not pad.exists():
        return True
    try:
        bekend = {c["bestand"] for c in json.loads(pad.read_text(encoding="utf-8"))["clips"]}
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return True
    return bekend != {q.name for q in media.vind_bronnen(p / "bronnen")}


def verwerk(
    project: str,
    *,
    stijl: str = "landschap",
    opnieuw: bool = False,
    melder=None,
) -> threading.Thread:
    """Ingest + analyse in de achtergrond, met voortgang voor de interface.

    `melder(soort, data)` wordt geroepen met soort "voortgang", "klaar" of
    "fout". De oude Studio liet de browser pollen op `is_bezig()`; de app wil
    het geduwd krijgen over stdio. Beide werken: `zet_bezig` blijft gevuld.
    """
    from .analyse import analyseer
    from .ingest import ingest as _ingest

    def meld(stap: str, tekst: str, gedaan: int = 0, totaal: int = 0) -> None:
        zet_bezig(project, tekst)
        if melder is not None:
            melder(
                "voortgang",
                {
                    "werk": "verwerk",
                    "project": project,
                    "stap": stap,
                    "gedaan": gedaan,
                    "totaal": totaal,
                    "tekst": tekst,
                },
            )

    def logger(stap: str, kop: str):
        def log(ruw) -> None:
            t = str(ruw).strip()
            m = _TELLER.search(t)
            gedaan, totaal = (int(m[1]), int(m[2])) if m else (0, 0)
            meld(stap, f"{kop} — {t}" if t else kop, gedaan, totaal)

        return log

    def werk():
        try:
            paths.project_dir(project)
            if moet_inlezen(project, opnieuw=opnieuw):
                meld("inlezen", "Beelden inlezen…")
                _ingest(project, overschrijf=opnieuw, log=logger("inlezen", "Beelden inlezen"))
            meld("analyseren", "Analyseren…")
            analyseer(project, stijl=stijl, log=logger("analyseren", "Analyseren"))
        except Exception as e:  # noqa: BLE001
            import sys as _sys
            import traceback as _tb

            # Naar het engine-log: zonder regelnummer is 'NaN to integer' raden.
            _tb.print_exc(file=_sys.stderr)
            zet_bezig(project, f"FOUT: {e}")
            if melder is not None:
                melder(
                    "fout",
                    {"werk": "verwerk", "project": project,
                     "fout": str(e), "soort": type(e).__name__},
                )
            return
        zet_bezig(project, None)
        if melder is not None:
            melder(
                "klaar",
                {"werk": "verwerk", "project": project, "status": naar_dict(status(project))},
            )

    draad = threading.Thread(target=werk, daemon=True)
    draad.start()
    return draad


def naar_dict(s: Status) -> dict:
    return {
        "naam": s.naam,
        "aantal_clips": s.aantal_clips,
        "totaal_duur": round(s.totaal_duur, 1),
        "heeft_muziek": s.heeft_muziek,
        "muziek": s.muziek,
        "is_ingelezen": s.is_ingelezen,
        "is_geanalyseerd": s.is_geanalyseerd,
        "heeft_montage": s.heeft_montage,
        "renders": s.renders,
        "gewijzigd": s.gewijzigd,
        "bezig": s.bezig,
        "stap": s.stap,
        "klaar": s.klaar_om_te_monteren,
    }
