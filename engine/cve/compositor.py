"""De native compositor: de enige weg waarlangs kleur en afwerking gaan.

Hij staat standaard aan zodra het binary er is. `BEATCUT_COMPOSITOR=0` zet hem
uit; dan doen de ffmpeg-look-filters het werk weer. Ontbreekt het binary, dan
valt de render daar ook op terug, maar met een waarschuwing in het log én in
`cve doctor` — want die twee paden zijn níet gelijk (gemeten 03-10-2026:
ΔE2000 gemiddeld 4,0 en maximaal 15,4), en dan is "voorvertoning = export"
niet meer waar.

Waarom dit de enige weg is: de live speler in de webview leest dezelfde twee
WGSL-bestanden uit `app/shaders/` in (zie `app/src/speler/tekenen.ts`). Zolang
de export door deze compositor gaat, rekenen stap Look, de speler en de
uiteindelijke mp4 met letterlijk dezelfde shaders (PLAN-v2 §4.4).

De keten voor een hele video is drie processen in een pijp:

    ffmpeg (decoderen) → beatcut-compositor (kleur en afwerking) → ffmpeg (encoderen)

Rauwe RGBA ertussen, dus geen tussenliggende compressie die kleur kost.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from . import media, paths
from .edl import Afwerking, Canvas, Look

GEMETEN_VERSCHIL = "ΔE2000 gemiddeld 4,0 en maximaal 15,4 (gemeten 03-10-2026)"


def binary() -> Path | None:
    """Waar het binary staat, of None als het er niet is.

    In de ontwikkelboom gaat de cargo-map vóór: `cargo build --release` is
    genoeg om hem te gebruiken, zonder kopieerstap. Dat is de volgorde sinds
    03-10-2026 — daarvóór kwam `installer/uit/compositor/` eerst en kon een
    oude kopie daar een verse bouw stil overschaduwen, waarna de hele
    testsuite tegen een verouderd binary draaide.

    Daarna `paths._meegeleverde_mappen()`, dezelfde lijst waarlangs ffmpeg
    gevonden wordt: in een bevroren app `Resources/engine/bin/`, vanuit de
    broncode `installer/uit/compositor/` — dat blijft wat de installer en
    Tauri meenemen. Wil je tegen één specifiek binary draaien, zet dan
    `BEATCUT_COMPOSITOR_BIN`; die gaat voor alles.
    """
    naam = "beatcut-compositor.exe" if os.name == "nt" else "beatcut-compositor"
    env = os.environ.get("BEATCUT_COMPOSITOR_BIN")
    kandidaten = [Path(env)] if env else []
    if not getattr(sys, "frozen", False):
        kandidaten.append(paths.ROOT / "compositor" / "target" / "release" / naam)
    kandidaten += [d / naam for d in paths._meegeleverde_mappen()]
    return next((p for p in kandidaten if p.exists()), None)


def uitgezet() -> bool:
    """Of iemand hem met de hand heeft uitgezet (`BEATCUT_COMPOSITOR=0`)."""
    return os.environ.get("BEATCUT_COMPOSITOR", "").strip() == "0"


def aan() -> bool:
    """Of de compositor de look doet. Standaard: ja, als het binary er is."""
    return not uitgezet() and binary() is not None


def waarschuwing() -> str:
    """Wat er mis is, of "" als er niets aan de hand is.

    Alleen als het binary ontbreekt. Bewust uitzetten is een keuze en geen
    mankement, dus dan zwijgt hij.
    """
    if uitgezet() or binary() is not None:
        return ""
    return (
        "De native compositor ontbreekt; de look komt uit de ffmpeg-keten. "
        f"Die wijkt zichtbaar af van wat stap Look toont ({GEMETEN_VERSCHIL}). "
        "Bouw hem met: cargo build --release --manifest-path compositor/Cargo.toml"
    )


@lru_cache(maxsize=4)
def _info(exe: str, stempel: tuple[int, int]) -> dict:
    """`--info` van het binary. Op pad plus mtime/grootte, dus een herbouw
    levert een nieuwe uitkomst in plaats van de oude uit de cache."""
    del stempel  # alleen om de cache te breken
    try:
        r = subprocess.run([exe, "--info"], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)
    except Exception as e:  # noqa: BLE001
        return {"versie": "?", "adapter": f"onbekend ({e})", "backend": "?"}


def info() -> dict | None:
    """Versie, adapternaam en backend (Metal / Dx12 / Vulkan / software)."""
    exe = binary()
    if exe is None:
        return None
    s = exe.stat()
    return _info(str(exe), (int(s.st_mtime), s.st_size))


def sleutel() -> str:
    """Korte vingerafdruk van wie de kleur rekent. Voor cachesleutels.

    Niet alleen de versie uit `Cargo.toml`: de shaders zitten met `include_str!`
    in het binary, dus een shaderwijziging verandert het bestand maar niet het
    versienummer. Mtime en grootte erbij, en dan verloopt de cache precies bij
    een herbouw.
    """
    exe = binary()
    if not aan() or exe is None:
        return "ffmpeg"
    s = exe.stat()
    return f"compositor-{(info() or {}).get('versie', '?')}-{int(s.st_mtime)}-{s.st_size}"


def _exe() -> Path:
    exe = binary()
    if exe is None:
        raise FileNotFoundError(
            "het compositor-binary ontbreekt. Bouw het met: "
            "cargo build --release --manifest-path compositor/Cargo.toml"
        )
    return exe


def _argumenten(breedte: int, hoogte: int, look: Look, afw: Afwerking,
                seed: int, aantal: int, vanaf: int) -> list[str]:
    """De vaste set vlaggen. Eén plek, zodat de losse frames van
    `looks.voorbeeld()` en de hele video nooit anders gestuurd worden."""
    from . import looks as lookcatalogus

    lut = lookcatalogus.lut_pad(look.id)
    return [
        str(_exe()),
        "--breedte", str(breedte),
        "--hoogte", str(hoogte),
        "--aantal", str(aantal),
        "--lut", str(lut) if lut else "geen",
        "--sterkte", f"{max(0.0, min(1.0, look.sterkte)):.4f}",
        "--afwerking", json.dumps(asdict(afw)),
        "--seed", str(seed),
        "--vanaf", str(vanaf),
    ]


def _overgangargumenten(overgangen: list[dict], staart: Path | None, ff: str,
                        fps: int, doel: Path) -> list[str]:
    """De overgangsvlaggen, met de lijst zelf in een bestand.

    Zie `render._overgangen()`: per overgang het eerste frame van blok B, het
    aantal mengframes, de duur in frames en de soort; de staarten van de
    uitgaande blokken staan in die volgorde in `staart`.

    De lijst gaat niet mee op de commandoregel. Windows kapt een commandoregel
    af op 32.767 tekens, en vijf minuten montage met shots van een halve
    seconde geeft 600 overgangen - alleen die JSON is al ruim 34.000 tekens.
    Dan start de compositor helemaal niet meer.
    """
    pad = doel.parent / f"{doel.stem}-overgangen.json"
    pad.write_text(json.dumps(overgangen), encoding="utf-8")
    return ["--overgangen-bestand", str(pad), "--staart", str(staart),
            "--ffmpeg", ff, "--fps", str(fps)]


def frames(rgba: bytes, breedte: int, hoogte: int, look: Look, afw: Afwerking,
           *, seed: int = 0, vanaf: int = 0, timeout: int = 600) -> bytes:
    """Een paar losse frames door de compositor. Rauwe RGBA in en uit.

    Voor `looks.voorbeeld()` en de gouden-frames-poort. Een hele video gaat via
    `pas_toe()`, want dan hoort er geen 8 MB per frame door Python te lopen.
    """
    stap = breedte * hoogte * 4
    aantal, rest = divmod(len(rgba), stap)
    if aantal < 1 or rest:
        raise ValueError(f"{len(rgba)} bytes is geen heel aantal frames van {stap}")
    r = subprocess.run(
        _argumenten(breedte, hoogte, look, afw, seed, aantal, vanaf),
        input=rgba, capture_output=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"compositor faalde: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    if len(r.stdout) != len(rgba):
        raise RuntimeError(f"compositor gaf {len(r.stdout)} bytes, verwacht {len(rgba)}")
    return r.stdout


def pas_toe(bron: Path, doel: Path, look: Look, afw: Afwerking, canvas: Canvas,
            seed: int = 0, *, encoder: tuple[str, list[str]] | None = None,
            overgangen: list[dict] | None = None, staart: Path | None = None,
            timeout: int = 3600) -> Path:
    """Een hele video door de compositor halen en opnieuw encoderen.

    Hij hangt achteraan, na het aan elkaar plakken van de blokken: dan telt de
    frame-index door over de hele tijdlijn en loopt de filmtrilling niet per
    shot opnieuw aan.

    `encoder` komt uit `render._encoder_voor()`, zodat de eindexport dezelfde
    hardware-encoder en dezelfde meeschalende bitrate krijgt als de rest van de
    render. Nooit libx264 vastzetten: de meegeleverde LGPL-ffmpeg heeft hem niet.
    """
    enc, enc_opties = encoder if encoder is not None else media.video_encoder()
    ff = str(paths.ffmpeg())
    b, h = canvas.breedte, canvas.hoogte

    decode = comp = encode = None
    klacht: list[bytes] = []
    try:
        decode = subprocess.Popen(
            [ff, "-v", "error", "-i", str(bron), "-map", "0:v:0", "-an",
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            stdout=subprocess.PIPE,
        )
        args = _argumenten(b, h, look, afw, seed, 0, 0)
        if overgangen:
            args += _overgangargumenten(overgangen, staart, ff, canvas.fps, doel)
        comp = subprocess.Popen(
            args,
            stdin=decode.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        decode.stdout.close()  # alleen de compositor houdt het leeseinde vast
        # Meteen meelezen, niet pas na afloop: een pijp die niemand leest loopt
        # vol op 64 kB en zet de schrijver stil. Dan wacht de compositor op
        # ruimte in stderr, de encoder op beeld, en wij op de encoder.
        meelezer = threading.Thread(
            target=lambda: klacht.append(comp.stderr.read() or b""), daemon=True
        )
        meelezer.start()
        encode = subprocess.Popen(
            [ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
             "-s", f"{b}x{h}", "-r", str(canvas.fps), "-i", "-",
             "-i", str(bron), "-map", "0:v:0", "-map", "1:a?", "-c:a", "copy",
             "-c:v", enc, *enc_opties,
             "-pix_fmt", "yuv420p",
             "-video_track_timescale", str(int(canvas.fps * 1000)), str(doel)],
            stdin=comp.stdout,
        )
        comp.stdout.close()
        encode.wait(timeout=timeout)
        comp.wait(timeout=60)
        decode.wait(timeout=60)
        meelezer.join(timeout=30)
    finally:
        # Ook bij een timeout of een fout halverwege: niets laat je draaien.
        # Van achter naar voren, zodat de voorganger stopt op een gesloten pijp
        # in plaats van door te rekenen voor niemand.
        for proces in (encode, comp, decode):
            if proces is not None and proces.poll() is None:
                proces.kill()
                proces.wait()
    if comp.returncode != 0:
        melding = (klacht[0] if klacht else b"").decode("utf-8", "replace")[-300:]
        raise RuntimeError(f"compositor faalde: {melding}")
    if encode.returncode != 0 or not doel.exists():
        raise RuntimeError("het encoderen na de compositor faalde")
    return doel
