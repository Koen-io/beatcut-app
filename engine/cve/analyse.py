"""Fase 1 - orkestratie van de analyse.

Voegt beeld, audio en muziek samen tot een `analysis.json`. Dat bestand is de
enige invoer voor de regie-stap. Bewust twee lagen:

  clips[].shots[]    per shot een samenvatting - dit leest het model
  clips[].reeks      metingen per meetmoment - dit leest de scorer en de GUI

Zo blijft de leesbare laag klein terwijl de precisie behouden blijft.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import media, paths
from .analyze import beeld as beeld_mod
from .analyze import muziek as muziek_mod
from .analyze import segmenten as seg_mod
from .analyze import telemetrie as telemetrie_mod


def _analyseer_een(args: tuple[str, str]) -> tuple[str, dict]:
    """Draait in een apart proces: OpenCV is CPU-werk en laat de GIL niet los."""
    clip_id, proxy_pad, bron_pad = args
    proxy = Path(proxy_pad)
    b = beeld_mod.analyseer_clip(proxy)
    b.shots = beeld_mod.detecteer_shots(proxy)

    tel = telemetrie_mod.lees(Path(bron_pad))
    op_lijn = telemetrie_mod.op_tijdlijn(tel, b.tijden)

    return clip_id, {
        "duur": b.duur,
        "fps": b.fps,
        "shots": beeld_mod.per_shot_samenvatting(b),
        "telemetrie": {
            "bron": tel.bron,
            "sporen": tel.sporen,
            "heeft_licht": tel.heeft_licht,
            "heeft_gezichten": tel.heeft_gezichten,
            **op_lijn,
        },
        "reeks": {
            "tijden": b.tijden,
            "scherpte": b.scherpte,
            "belichting": b.belichting,
            "beweging": b.beweging,
            "shake": b.shake,
            "vlakheid": b.vlakheid,
            "hashes": b.hashes,
            "kleur": [list(k) for k in b.kleur],
        },
    }


def _clip_audio(proxy: Path, cache: Path) -> dict:
    """Lichte audio-analyse per clip: waar is het stil, waar niet."""
    wav = media.haal_audio(proxy, cache / f"{proxy.stem}.wav")
    if wav is None:
        return {"heeft_audio": False, "stiltes": [], "aandeel_stil": 1.0}
    stil = media.stiltes(wav)
    info = media.probe(wav)
    stil_tijd = sum(b - a for a, b in stil)
    return {
        "heeft_audio": True,
        "stiltes": [[round(a, 2), round(b, 2)] for a, b in stil],
        "aandeel_stil": round(stil_tijd / info.duur, 3) if info.duur else 1.0,
    }


SCENE_GAT_MINUTEN = 12.0


def _groepeer_scenes(clips: list[dict], *, log=print) -> None:
    """Deel clips in scenes op basis van opnametijd.

    Waarom dit beter werkt dan beeldvergelijking: twee opnames van hetzelfde
    tafereel vanuit een andere hoek hebben een heel andere vingerafdruk, maar
    liggen wel twee minuten uit elkaar. De klok van de camera weet dat je nog
    op dezelfde plek stond; de pixels weten dat niet.
    """
    from datetime import datetime

    def moment(c: dict) -> datetime | None:
        s = c.get("opgenomen")
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    met_tijd = [(c, moment(c)) for c in clips]
    if not any(t for _, t in met_tijd):
        for i, c in enumerate(clips):
            c["scene"] = i
        return

    scene = 0
    vorige = None
    for c, t in met_tijd:
        if t is None:
            c["scene"] = scene
            continue
        if vorige is not None:
            gat = abs((t - vorige).total_seconds()) / 60.0
            if gat > SCENE_GAT_MINUTEN:
                scene += 1
        c["scene"] = scene
        vorige = t

    aantal = len({c["scene"] for c in clips})
    log(f"Scenes: {aantal} groepen uit {len(clips)} clips (gat > {SCENE_GAT_MINUTEN:.0f} min)")


def analyseer(
    project: str,
    *,
    workers: int = 6,
    met_clip_audio: bool = True,
    stijl: str = "actie",
    log=print,
) -> dict:
    pdir = paths.project_dir(project)
    ingest_pad = pdir / "ingest.json"
    if not ingest_pad.exists():
        raise RuntimeError(f"Geen ingest.json in {pdir}. Draai eerst: cve ingest {project}")

    ing = json.loads(ingest_pad.read_text(encoding="utf-8"))
    proxymap = pdir / "proxies"
    cache = pdir / "cache"

    bronmap = pdir / "bronnen"
    taken = [
        (c["id"], str(proxymap / c["proxy"]), str(bronmap / c["bestand"])) for c in ing["clips"]
    ]
    log(f"Beeldanalyse op {len(taken)} clips ({workers} processen)...")

    resultaten: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyseer_een, t): t[0] for t in taken}
        klaar = 0
        for f in as_completed(futures):
            cid, data = f.result()
            resultaten[cid] = data
            klaar += 1
            log(f"  [{klaar}/{len(taken)}] {cid}  {len(data['shots'])} shot(s)")

    if met_clip_audio:
        log("Audio per clip...")
        for c in ing["clips"]:
            if c["heeft_audio"]:
                resultaten[c["id"]]["audio"] = _clip_audio(proxymap / c["proxy"], cache)
            else:
                resultaten[c["id"]]["audio"] = {
                    "heeft_audio": False,
                    "stiltes": [],
                    "aandeel_stil": 1.0,
                }

    clips = []
    for c in ing["clips"]:
        r = resultaten[c["id"]]
        clips.append(
            {
                "id": c["id"],
                "bestand": c["bestand"],
                "proxy": c["proxy"],
                "duur": r["duur"],
                "fps_bron": c["fps"],
                "breedte": c["breedte"],
                "hoogte": c["hoogte"],
                "verticaal": c["verticaal"],
                "opgenomen": c["opgenomen"],
                "apparaat": c["apparaat"],
                "shots": r["shots"],
                "audio": r.get("audio", {}),
                "telemetrie": r["telemetrie"],
                "reeks": r["reeks"],
            }
        )

    _groepeer_scenes(clips, log=log)

    mz = None
    muziekbestanden = media.vind_muziek(pdir / "muziek")
    if muziekbestanden:
        log(f"Muziekanalyse: {muziekbestanden[0].name}")
        m = muziek_mod.analyseer(muziekbestanden[0])
        mz = asdict(m)
        mz["snijraster"] = muziek_mod.snijraster(m)

    data = {
        "versie": 1,
        "project": project,
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kalibratie": "iphone-4k60-540p30",
        "totaal_duur": ing["totaal_duur"],
        "muziek": mz,
        "clips": clips,
    }

    # Segmentkandidaten: de beste stukken binnen elke clip.
    from . import stijl as stijl_mod

    st = stijl_mod.laad(stijl, paths.STYLES)
    gewichten = seg_mod.Gewichten(**st.gewichten.__dict__)
    ruw = seg_mod.alle_kandidaten(data, gewichten)
    schoon = seg_mod.ontdubbel(ruw)
    log(f"Segmenten: {len(ruw)} kandidaten, {len(schoon)} na ontdubbelen")
    data["stijl"] = stijl
    data["gewichten"] = gewichten.__dict__
    data["segmenten"] = [
        {
            "clip": s.clip,
            "scene": s.scene,
            "start": s.start,
            "eind": s.eind,
            "duur": s.duur,
            "score": s.score,
            "onderdelen": s.onderdelen,
        }
        for s in schoon
    ]

    uit = pdir / "analysis.json"
    uit.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"\nGeschreven: {uit}  ({uit.stat().st_size / 1024:.0f} KB)")
    return data


def samenvatting(data: dict, *, breed: bool = False) -> str:
    """Compacte, modelvriendelijke samenvatting. Dit is wat de regisseur leest."""
    regels: list[str] = []
    mz = data.get("muziek")
    if mz:
        regels.append(
            f"MUZIEK  {mz['bpm']:.0f} BPM  ·  {mz['duur']:.0f}s  ·  "
            f"{len(mz['maten'])} maten  ·  drops op "
            + ", ".join(f"{d:.0f}s" for d in mz["drops"])
        )
        for s in mz["secties"]:
            regels.append(
                f"        {s['start']:6.1f}-{s['eind']:6.1f}s  {s['niveau']:7}  e={s['energie']:.2f}"
            )
        regels.append("")

    regels.append(
        f"CLIPS  {len(data['clips'])} stuks  ·  {data['totaal_duur'] / 60:.1f} min ruw materiaal"
    )
    regels.append(
        f"{'id':4}{'duur':>7}{'scherp':>7}{'belicht':>8}{'beweg':>7}{'shake':>7}"
        f"{'lux':>9}{'gez':>4}  vorm"
    )
    for c in data["clips"]:
        vorm = "9:16" if c["verticaal"] else "16:9"
        tel = c.get("telemetrie", {})
        lux = tel.get("lux") or []
        lux_med = f"{sorted(lux)[len(lux) // 2]:.0f}" if lux else "-"
        gez = max(tel.get("gezichten") or [0])
        for s in c["shots"]:
            regels.append(
                f"{c['id']:4}{s['duur']:>7.1f}{s['scherpte']:>7.2f}{s['belichting']:>8.2f}"
                f"{s['beweging']:>7.2f}{s['shake']:>7.2f}{lux_med:>9}{gez:>4}  {vorm}"
            )

    segs = data.get("segmenten") or []
    if segs:
        regels.append("")
        regels.append(f"SEGMENTEN  {len(segs)} kandidaten, stijl '{data.get('stijl')}'")
        regels.append(f"{'clip':6}{'start':>7}{'duur':>6}{'score':>7}  grootste bijdrage")
        gew = data.get("gewichten", {})
        for s in segs[:25]:
            # Sorteer op werkelijke bijdrage (gewicht x waarde), niet op de
            # ruwe waarde. Anders staat een signaal met gewicht 0 bovenaan.
            bijdrage = {k: gew.get(k, 0.0) * v for k, v in s["onderdelen"].items()}
            top = sorted(bijdrage.items(), key=lambda kv: -abs(kv[1]))[:3]
            uitleg = "  ".join(f"{k}{v:+.2f}" for k, v in top if abs(v) > 0.001)
            regels.append(
                f"{s['clip']:6}{s['start']:>7.1f}{s['duur']:>6.1f}{s['score']:>7.3f}  {uitleg}"
            )
        if len(segs) > 25:
            regels.append(f"... en nog {len(segs) - 25}")
    return "\n".join(regels)
