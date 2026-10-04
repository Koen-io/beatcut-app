"""Fase 2 - telemetrie uit de camera zelf.

Camera's schrijven meetgegevens mee die veel betrouwbaarder zijn dan wat we uit
de pixels kunnen afleiden. Deze module leest die uit, zonder externe tools.

Ondersteund:
  Apple (iPhone/iPad)  `mebx` timed-metadata sporen in .MOV
                       - scene-illuminance  (milli-lux, per frame)
                       - detected-face      (aanwezigheid + tijdstippen)
                       - video-orientation
  GoPro                GPMF-spoor  (voorbereid, nog niet geimplementeerd)
  DJI                  losse .SRT-bestanden naast de video

Waarom zelf parsen: ffmpeg kan `mebx` niet uitpakken en externe parsers zijn
platformgebonden. Dit is pure Python en werkt dus ook op Windows.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

APPLE_NS = rb"com\.apple\.quicktime\.[a-z0-9.\-]+"


# --------------------------------------------------------------------------
# Kleine ISO-BMFF-lezer. Alleen wat we nodig hebben.
# --------------------------------------------------------------------------


def _kinderen(buf: bytes, start: int, eind: int) -> list[tuple[str, int, int]]:
    uit: list[tuple[str, int, int]] = []
    p = start
    while p < eind - 8:
        try:
            grootte = struct.unpack(">I", buf[p : p + 4])[0]
            soort = buf[p + 4 : p + 8].decode("latin1")
        except (struct.error, UnicodeDecodeError):
            break
        if grootte < 8 or p + grootte > eind:
            break
        uit.append((soort, p, grootte))
        p += grootte
    return uit


def _lees_moov(pad: Path) -> bytes | None:
    """Haal het moov-atoom op. Werkt of het nu voor- of achteraan staat."""
    grootte_bestand = pad.stat().st_size
    with pad.open("rb") as f:
        p = 0
        while p < grootte_bestand - 8:
            f.seek(p)
            kop = f.read(8)
            if len(kop) < 8:
                return None
            grootte = struct.unpack(">I", kop[:4])[0]
            soort = kop[4:8]
            if grootte == 1:
                grootte = struct.unpack(">Q", f.read(8))[0]
            if grootte < 8:
                return None
            if soort == b"moov":
                f.seek(p)
                return f.read(grootte)
            p += grootte
    return None


@dataclass
class Spoor:
    naam: str
    tijdschaal: int
    tijden: list[float]
    monsters: list[tuple[int, int]]  # (offset in bestand, lengte)


def _sporen(moov: bytes) -> list[Spoor]:
    """Alle timed-metadata sporen met hun monsterposities."""
    uit: list[Spoor] = []
    for soort, tp, ts in _kinderen(moov, 8, len(moov)):
        if soort != "trak":
            continue
        mdia = [c for c in _kinderen(moov, tp + 8, tp + ts) if c[0] == "mdia"]
        if not mdia:
            continue
        _, mp, ms = mdia[0]

        hdlr = [c for c in _kinderen(moov, mp + 8, mp + ms) if c[0] == "hdlr"]
        if not hdlr or moov[hdlr[0][1] + 16 : hdlr[0][1] + 20] != b"meta":
            continue

        mdhd = [c for c in _kinderen(moov, mp + 8, mp + ms) if c[0] == "mdhd"]
        tijdschaal = struct.unpack(">I", moov[mdhd[0][1] + 20 : mdhd[0][1] + 24])[0] if mdhd else 600

        minf = [c for c in _kinderen(moov, mp + 8, mp + ms) if c[0] == "minf"]
        if not minf:
            continue
        stbl = [c for c in _kinderen(moov, minf[0][1] + 8, minf[0][1] + minf[0][2]) if c[0] == "stbl"]
        if not stbl:
            continue
        K = {c[0]: (c[1], c[2]) for c in _kinderen(moov, stbl[0][1] + 8, stbl[0][1] + stbl[0][2])}
        if not {"stsd", "stsz", "stts"} <= K.keys():
            continue

        # naam uit de mebx-sleuteltabel
        sp, ss = K["stsd"]
        blok = moov[sp : sp + ss]
        treffer = re.search(APPLE_NS, blok)
        naam = treffer.group(0).decode() if treffer else "onbekend"

        # monstergroottes
        p, _ = K["stsz"]
        vast = struct.unpack(">I", moov[p + 12 : p + 16])[0]
        aantal = struct.unpack(">I", moov[p + 16 : p + 20])[0]
        if vast:
            groottes = [vast] * aantal
        else:
            groottes = [
                struct.unpack(">I", moov[p + 20 + i * 4 : p + 24 + i * 4])[0] for i in range(aantal)
            ]

        # brokoffsets
        if "stco" in K:
            p2, _ = K["stco"]
            n = struct.unpack(">I", moov[p2 + 12 : p2 + 16])[0]
            offsets = [struct.unpack(">I", moov[p2 + 16 + i * 4 : p2 + 20 + i * 4])[0] for i in range(n)]
        elif "co64" in K:
            p2, _ = K["co64"]
            n = struct.unpack(">I", moov[p2 + 12 : p2 + 16])[0]
            offsets = [struct.unpack(">Q", moov[p2 + 16 + i * 8 : p2 + 24 + i * 8])[0] for i in range(n)]
        else:
            continue

        # monsters per brok
        p3, _ = K["stsc"]
        n3 = struct.unpack(">I", moov[p3 + 12 : p3 + 16])[0]
        stsc = [
            struct.unpack(">III", moov[p3 + 16 + i * 12 : p3 + 28 + i * 12]) for i in range(n3)
        ]

        monsters: list[tuple[int, int]] = []
        si = 0
        for ci, brok_off in enumerate(offsets):
            per_brok = 1
            for eerste, per, _ in stsc:
                if ci + 1 >= eerste:
                    per_brok = per
            o = brok_off
            for _ in range(per_brok):
                if si >= len(groottes):
                    break
                monsters.append((o, groottes[si]))
                o += groottes[si]
                si += 1

        # tijden
        p4, _ = K["stts"]
        n4 = struct.unpack(">I", moov[p4 + 12 : p4 + 16])[0]
        tijden: list[float] = []
        t = 0
        for i in range(n4):
            cnt, duur = struct.unpack(">II", moov[p4 + 16 + i * 8 : p4 + 24 + i * 8])
            for _ in range(cnt):
                tijden.append(t / tijdschaal)
                t += duur

        uit.append(Spoor(naam, tijdschaal, tijden, monsters))
    return uit


# --------------------------------------------------------------------------
# Betekenis geven aan de monsters
# --------------------------------------------------------------------------


@dataclass
class Telemetrie:
    bron: str = "geen"
    apparaat: str | None = None
    # licht
    lux_tijden: list[float] = field(default_factory=list)
    lux: list[float] = field(default_factory=list)
    # gezichten
    gezicht_tijden: list[float] = field(default_factory=list)
    gezicht_aantal: list[int] = field(default_factory=list)
    # ruwe sporen die we herkenden maar niet uitpakken
    sporen: list[str] = field(default_factory=list)

    @property
    def heeft_licht(self) -> bool:
        return bool(self.lux)

    @property
    def heeft_gezichten(self) -> bool:
        return any(self.gezicht_aantal)


def _lees_apple(pad: Path, moov: bytes) -> Telemetrie:
    tel = Telemetrie(bron="apple")
    sporen = _sporen(moov)
    tel.sporen = [s.naam for s in sporen]

    with pad.open("rb") as f:
        for spoor in sporen:
            if spoor.naam.endswith("scene-illuminance"):
                for i, (off, lengte) in enumerate(spoor.monsters):
                    if lengte < 12 or i >= len(spoor.tijden):
                        continue
                    f.seek(off)
                    ruw = f.read(lengte)
                    # (grootte, sleutelindex, waarde) - waarde is milli-lux
                    milli = struct.unpack(">I", ruw[8:12])[0]
                    tel.lux_tijden.append(round(spoor.tijden[i], 3))
                    tel.lux.append(round(milli / 1000.0, 1))

            elif "detected-face" in spoor.naam:
                for i, (off, lengte) in enumerate(spoor.monsters):
                    if i >= len(spoor.tijden):
                        continue
                    f.seek(off)
                    ruw = f.read(lengte)
                    # Een leeg monster is 8 bytes (kop zonder inhoud) = geen gezicht.
                    # Elk gezicht levert een `crec`-blok op.
                    aantal = len(re.findall(b"crec", ruw))
                    tel.gezicht_tijden.append(round(spoor.tijden[i], 3))
                    tel.gezicht_aantal.append(aantal)

    return tel


def lees(pad: Path) -> Telemetrie:
    """Lees telemetrie uit een videobestand. Geeft altijd een object terug."""
    # DJI schrijft een los .SRT-bestand naast de video
    srt = pad.with_suffix(".SRT")
    if not srt.exists():
        srt = pad.with_suffix(".srt")

    moov = None
    if pad.suffix.lower() in (".mov", ".mp4", ".m4v"):
        try:
            moov = _lees_moov(pad)
        except (OSError, struct.error):
            moov = None

    if moov and re.search(APPLE_NS, moov):
        tel = _lees_apple(pad, moov)
        if srt.exists():
            tel.sporen.append("dji-srt (nog niet uitgelezen)")
        return tel

    if moov and b"GPMF" in moov:
        return Telemetrie(bron="gopro-gpmf-nog-niet-geimplementeerd")

    if srt.exists():
        return Telemetrie(bron="dji-srt-nog-niet-geimplementeerd")

    return Telemetrie(bron="geen")


def op_tijdlijn(tel: Telemetrie, tijden: list[float]) -> dict[str, list[float]]:
    """Bemonster de telemetrie op dezelfde tijdstippen als de beeldanalyse.

    Zo kunnen beeld en telemetrie later zonder gedoe opgeteld worden.
    """
    import numpy as np

    uit: dict[str, list[float]] = {}
    if not tijden:
        return uit

    doel = np.asarray(tijden, dtype=float)

    if tel.lux:
        bron_t = np.asarray(tel.lux_tijden)
        waarden = np.asarray(tel.lux)
        uit["lux"] = [round(float(v), 1) for v in np.interp(doel, bron_t, waarden)]
        # Genormaliseerde lichtscore: log-schaal, want lux is dat ook.
        # 10 lux = schemerig binnen, 1000 = goed binnen, 20000+ = buiten zon.
        log = np.log10(np.clip(uit["lux"], 1.0, None))
        uit["licht"] = [round(float(min(1.0, max(0.0, (v - 1.0) / 3.3))), 4) for v in log]

    if tel.gezicht_tijden:
        bron_t = np.asarray(tel.gezicht_tijden)
        waarden = np.asarray(tel.gezicht_aantal, dtype=float)
        # Vasthouden tot de volgende meting: gezichtsdata is spaarzaam geschreven.
        idx = np.searchsorted(bron_t, doel, side="right") - 1
        idx = np.clip(idx, 0, len(waarden) - 1)
        uit["gezichten"] = [int(waarden[i]) for i in idx]

    return uit
