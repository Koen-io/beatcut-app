"""Fase 1a - ingest.

Scant `bronnen/`, leest metadata, maakt proxies. Bronbestanden worden nooit
aangeraakt. Resultaat gaat naar `ingest.json` in de projectmap.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import geo, media, paths
from .doorvoer import Meter

PROXY_HOOGTE = 540
PROXY_FPS = 30
FASE = "inlezen"


@dataclass
class Clip:
    id: str
    bestand: str
    proxy: str
    duur: float
    fps: float
    breedte: int
    hoogte: int
    rotatie: int
    codec: str
    heeft_audio: bool
    verticaal: bool
    opgenomen: str | None
    apparaat: str | None
    data_sporen: int
    bytes: int
    # Waar de opname gemaakt is, als de camera dat opschreef. Blijft leeg
    # wanneer locatievoorzieningen uitstonden - dat is geen fout.
    locatie: dict | None = None


# De toewijzing bestandsnaam -> clip-id. Die hoort op schijf en niet in de
# nummering: `_clip_id` nummerde chronologisch op opnametijd, dus één clip
# erbij schoof alle id's op en een bestaande `edl.json` wees daarna naar andere
# beelden. Een id blijft nu van een bestand zolang het bestand er is.
CLIP_IDS = "clips.json"


def _clip_id(nummer: int) -> str:
    return f"C{nummer:02d}"


def _nummer(clip_id: str) -> int:
    try:
        return int(clip_id.lstrip("C"))
    except ValueError:
        return 0


def wijs_ids_toe(pdir: Path, namen: list[str]) -> dict[str, str]:
    """Geef elk bronbestand zijn id. Bekende namen houden het hunne.

    Nieuwe bestanden krijgen het volgende vrije nummer: één hoger dan het
    hoogste dat ooit is uitgedeeld. Nummers van verwijderde bestanden worden
    niet hergebruikt, want dan zou een oude `edl.json` naar het verkeerde
    beeld gaan wijzen.
    """
    pad = pdir / CLIP_IDS
    try:
        bekend: dict[str, str] = json.loads(pad.read_text(encoding="utf-8"))["ids"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        bekend = _ids_uit_ingest(pdir)

    volgende = max((_nummer(i) for i in bekend.values()), default=0) + 1
    uit: dict[str, str] = {}
    for naam in namen:
        if naam in bekend:
            uit[naam] = bekend[naam]
        else:
            uit[naam] = bekend[naam] = _clip_id(volgende)
            volgende += 1

    pdir.mkdir(parents=True, exist_ok=True)
    pad.write_text(
        json.dumps({"versie": 1, "ids": bekend}, indent=1), encoding="utf-8"
    )
    return uit


def _ids_uit_ingest(pdir: Path) -> dict[str, str]:
    """De toewijzing zoals een project van vóór `clips.json` hem al had.

    Die projecten hebben geen `clips.json`, maar hun id's staan wél in
    `ingest.json` — en de proxies in `proxies/` zijn ernaar genoemd. Zonder
    deze overname begint de nummering opnieuw en pakt een clip die
    chronologisch vóóraan valt C01 af van de clip die hem al had: de
    bestaande proxy hoort dan bij andere beelden.
    """
    try:
        ing = json.loads((pdir / "ingest.json").read_text(encoding="utf-8"))
        clips = ing["clips"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return {}
    uit: dict[str, str] = {}
    for c in clips:
        naam, cid = c.get("bestand"), c.get("id")
        if isinstance(naam, str) and isinstance(cid, str):
            uit.setdefault(naam, cid)
    return uit


def _korte_fout(e: BaseException) -> str:
    """Eén regel voor in de interface: de eerste regel, zonder ffmpeg-lappen."""
    tekst = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return tekst[:160]


def _sorteer_sleutel(info: media.MediaInfo) -> tuple[str, str]:
    """Chronologisch op opnamemoment; valt terug op bestandsnaam."""
    return (info.opgenomen or "9999", info.pad.name)


def ingest(
    project: str,
    *,
    overschrijf: bool = False,
    workers: int = 4,
    log=print,
    meter: Meter | None = None,
) -> dict:
    """Lees alle bronnen in en maak proxies. Geeft het ingest-woordenboek terug.

    `meter` is optioneel en meet de doorvoer voor de tijdschatting in de
    interface. Ingest is de stap die de duur van elke clip te weten komt, dus
    dit is ook de plek waar de maat van de hele klus bekend wordt — zie
    `doorvoer.Meter.klus()`.
    """
    pdir = paths.project_dir(project)
    bronmap = pdir / "bronnen"
    proxymap = pdir / "proxies"

    bestanden = media.vind_bronnen(bronmap)
    if not bestanden:
        raise RuntimeError(f"Geen videobestanden gevonden in {bronmap}")

    log(f"{len(bestanden)} bronbestanden gevonden. Metadata lezen...")
    # Eén onleesbaar bestand (afgebroken kopie, exotische codec, 0 bytes)
    # hield daarvóór de hele ronde tegen: de andere twintig clips kwamen er
    # dan ook niet door. Nu gaat zo'n bestand opzij, mét de reden, en de
    # interface laat het zien in plaats van een rode balk over alles.
    infos: list[media.MediaInfo] = []
    overgeslagen: list[dict] = []
    for p in bestanden:
        try:
            info = media.probe(p)
            if info.duur <= 0 or info.breedte <= 0 or info.hoogte <= 0:
                raise ValueError("geen bruikbaar beeld (duur of maat is 0)")
        except Exception as e:  # noqa: BLE001 — de reden gaat mee naar de interface
            log(f"  overgeslagen: {p.name} — {e}")
            overgeslagen.append({"bestand": p.name, "fout": _korte_fout(e)})
            continue
        infos.append(info)
    if not infos:
        redenen = "; ".join(f"{o['bestand']}: {o['fout']}" for o in overgeslagen)
        raise RuntimeError(f"Geen van de videobestanden is te lezen ({redenen})")
    infos.sort(key=_sorteer_sleutel)

    ids = wijs_ids_toe(pdir, [info.pad.name for info in infos])

    clips: list[Clip] = []
    for info in infos:
        cid = ids[info.pad.name]
        clips.append(
            Clip(
                id=cid,
                bestand=info.pad.name,
                proxy=f"{cid}.mp4",
                duur=round(info.duur, 3),
                fps=round(info.fps, 3),
                breedte=info.breedte,
                hoogte=info.hoogte,
                rotatie=info.rotatie,
                codec=info.codec,
                heeft_audio=info.heeft_audio,
                verticaal=info.is_verticaal,
                opgenomen=info.opgenomen,
                apparaat=info.apparaat,
                data_sporen=info.data_sporen,
                bytes=info.pad.stat().st_size,
                locatie=geo.uit_tags(info.tags),
            )
        )

    encoder, _ = media.video_encoder()
    log(f"Proxies maken ({PROXY_HOOGTE}p{PROXY_FPS}, encoder: {encoder})...")

    def nog_omzetten(clip: Clip) -> bool:
        """Staat er al een bruikbare proxy? Zelfde voorwaarde als `maak_proxy`.

        De tijdschatting moet dit weten: een tweede ronde slaat tientallen
        clips in een oogwenk over, en zonder dit onderscheid meet de meter
        daar een doorvoer van duizend seconden per seconde en belooft daarna
        "nog 0 seconden" terwijl de enige nieuwe clip nog moet.
        """
        doel = proxymap / clip.proxy
        return overschrijf or not (doel.exists() and doel.stat().st_size > 0)

    paren = list(zip(clips, infos, strict=True))
    if meter is not None:
        meter.klus(sum(c.duur for c in clips))
        meter.plan(FASE, sum(c.duur for c, _ in paren if nog_omzetten(c)))

    def werk(paar: tuple[Clip, media.MediaInfo]) -> float:
        clip, info = paar
        te_doen = clip.duur if nog_omzetten(clip) else 0.0
        media.maak_proxy(
            info.pad,
            proxymap / clip.proxy,
            hoogte=PROXY_HOOGTE,
            fps=PROXY_FPS,
            overschrijf=overschrijf,
        )
        return te_doen

    klaar = 0
    mislukt: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(werk, paar): paar[0] for paar in paren}
        for f in as_completed(futures):
            clip = futures[f]
            try:
                gedaan = f.result()
            except Exception as e:  # noqa: BLE001 — één proxy die mislukt is niet de hele ronde
                gedaan = clip.duur
                mislukt.add(clip.id)
                log(f"  overgeslagen: {clip.bestand} — {e}")
                overgeslagen.append({"bestand": clip.bestand, "fout": _korte_fout(e)})
            if meter is not None:
                meter.boek(FASE, gedaan)
            klaar += 1
            log(f"  [{klaar}/{len(paren)}] {clip.id}")
    if mislukt:
        clips = [c for c in clips if c.id not in mislukt]
    if not clips:
        raise RuntimeError("Van geen enkele video kon een proxy gemaakt worden")

    muziek = [p.name for p in media.vind_muziek(pdir / "muziek")]

    totaal = sum(c.duur for c in clips)
    resultaat = {
        "versie": 1,
        "project": project,
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proxy": {"hoogte": PROXY_HOOGTE, "fps": PROXY_FPS, "encoder": encoder},
        "totaal_duur": round(totaal, 2),
        "muziek": muziek,
        "clips": [asdict(c) for c in clips],
        # Bestanden in `bronnen/` die niet mee konden, met de reden. De
        # interface toont ze grijs; de analyse en de regie kennen ze niet.
        "overgeslagen": overgeslagen,
    }

    (pdir / "ingest.json").write_text(
        json.dumps(resultaat, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return resultaat


def samenvatting(data: dict) -> str:
    """Korte, leesbare samenvatting voor in de terminal of voor het model."""
    clips = data["clips"]
    tot = data["totaal_duur"]
    regels = [
        f"Project: {data['project']}",
        f"{len(clips)} clips  ·  {tot / 60:.1f} min totaal  ·  proxy {data['proxy']['hoogte']}p{data['proxy']['fps']}",
    ]
    if data["muziek"]:
        regels.append(f"Muziek: {', '.join(data['muziek'])}")
    regels.append("")
    regels.append(f"{'id':4} {'duur':>7} {'res':>10} {'fps':>5}  bestand")
    for c in clips:
        res = f"{c['breedte']}x{c['hoogte']}"
        merk = " V" if c["verticaal"] else ""
        regels.append(
            f"{c['id']:4} {c['duur']:>6.1f}s {res:>10} {c['fps']:>5.0f}{merk}  {c['bestand']}"
        )
    return "\n".join(regels)
