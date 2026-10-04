"""Dunne, cross-platform laag rond ffmpeg/ffprobe.

Alles wat een subprocess naar ffmpeg is, hoort hier. De rest van de engine
roept nooit rechtstreeks ffmpeg aan.
"""

from __future__ import annotations

import json
import shutil
import os
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import paths

VIDEO_EXTENSIES = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm"}
AUDIO_EXTENSIES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

# --- Aanlevernorm voor geluid --------------------------------------------
# YouTube, Instagram, TikTok en Spotify normaliseren allemaal rond -14 LUFS.
# Harder aanleveren wint dus niets: het platform draait het terug, en wat je
# overhoudt is minder dynamiek. De true peak moet onder -1 dBTP blijven omdat
# de hercodering naar AAC de golfvorm iets kan optillen; op 0 dBFS klipt dat.
# Zowel de renderer (loudnorm) als de review gebruiken deze getallen, zodat
# meten en maken niet uit elkaar kunnen lopen.
LUFS_DOEL = -14.0
TRUE_PEAK_DOEL = -1.0
LRA_DOEL = 11.0


class MediaFout(RuntimeError):
    pass


def _draai(cmd: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        kort = (r.stderr or "").strip().splitlines()[-5:]
        raise MediaFout(f"{Path(cmd[0]).name} faalde: " + " | ".join(kort))
    return r


# Kandidaten in volgorde van voorkeur. Een encoder in `ffmpeg -encoders` zegt
# alleen dat hij is meegebouwd, niet dat de hardware er is: een Windows-pc
# zonder NVIDIA heeft h264_nvenc gewoon in de lijst, en een virtuele machine
# (Koens Windows-VM, de GitHub-runners) heeft geen VideoToolbox-sessie of GPU.
# Daarom wordt elke kandidaat met een echte mini-encode geprobeerd.
_KANDIDATEN: list[tuple[str, list[str]]] = [
    ("h264_videotoolbox", ["-b:v", "8M", "-allow_sw", "1"]),
    ("h264_nvenc", ["-preset", "p4", "-cq", "23"]),
    ("h264_qsv", ["-global_quality", "23"]),
    ("h264_amf", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "24"]),
    ("h264_mf", ["-b:v", "8M", "-hw_encoding", "1"]),
    ("h264_mf", ["-b:v", "8M"]),
    ("libx264", ["-preset", "veryfast", "-crf", "23"]),
    ("libopenh264", ["-b:v", "8M"]),
]
# Altijd aanwezig in elke ffmpeg-build; lelijk maar het levert een mp4.
_NOODUITGANG: tuple[str, list[str]] = ("mpeg4", ["-q:v", "3"])


def _werkt(encoder: str, opties: list[str]) -> bool:
    """Lukt een encode van drie frames echt? Alleen dat telt."""
    try:
        r = subprocess.run(
            [str(paths.ffmpeg()), "-hide_banner", "-v", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
             "-frames:v", "3", "-pix_fmt", "yuv420p",
             "-c:v", encoder, *opties, "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0


@lru_cache(maxsize=1)
def video_encoder() -> tuple[str, list[str]]:
    """De snelste h264-encoder die op déze machine echt werkt.

    Volgorde: VideoToolbox (macOS) -> NVENC -> QSV -> AMF -> Media Foundation
    (Windows, ook in een VM) -> libx264 -> OpenH264 -> mpeg4 als noodgreep.
    `BEATCUT_ENCODER=<naam>` forceert er één (voor tests en probleemmachines).
    """
    try:
        uit = subprocess.run(
            [str(paths.ffmpeg()), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:  # noqa: BLE001
        return _NOODUITGANG
    gedwongen = os.environ.get("BEATCUT_ENCODER", "").strip()
    for naam, opties in _KANDIDATEN:
        if gedwongen and naam != gedwongen:
            continue
        if f" {naam} " in uit and _werkt(naam, opties):
            return naam, list(opties)
    return _NOODUITGANG


@dataclass
class MediaInfo:
    pad: Path
    duur: float
    breedte: int = 0
    hoogte: int = 0
    fps: float = 0.0
    rotatie: int = 0
    codec: str = ""
    heeft_audio: bool = False
    audio_codec: str = ""
    opgenomen: str | None = None
    apparaat: str | None = None
    data_sporen: int = 0
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_verticaal(self) -> bool:
        b, h = self.breedte, self.hoogte
        if self.rotatie in (90, 270):
            b, h = h, b
        return h > b


def _breuk(s: str | None) -> float:
    if not s or "/" not in s:
        try:
            return float(s) if s else 0.0
        except ValueError:
            return 0.0
    t, n = s.split("/", 1)
    try:
        return float(t) / float(n) if float(n) else 0.0
    except ValueError:
        return 0.0


def probe(pad: Path) -> MediaInfo:
    """Lees technische gegevens van een mediabestand."""
    r = _draai(
        [
            str(paths.ffprobe()),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(pad),
        ],
        timeout=120,
    )
    d = json.loads(r.stdout)
    fmt = d.get("format", {})
    tags = {k: v for k, v in fmt.get("tags", {}).items()}

    info = MediaInfo(
        pad=pad,
        duur=float(fmt.get("duration", 0.0) or 0.0),
        opgenomen=tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time"),
        apparaat=tags.get("com.apple.quicktime.model"),
        tags=tags,
    )

    for s in d.get("streams", []):
        soort = s.get("codec_type")
        if soort == "video" and not info.breedte:
            info.breedte = int(s.get("width", 0) or 0)
            info.hoogte = int(s.get("height", 0) or 0)
            info.codec = s.get("codec_name", "")
            info.fps = _breuk(s.get("avg_frame_rate") or s.get("r_frame_rate"))
            # rotatie kan in tags of in side_data staan
            rot = s.get("tags", {}).get("rotate")
            if rot is None:
                for sd in s.get("side_data_list", []) or []:
                    if "rotation" in sd:
                        rot = sd["rotation"]
                        break
            try:
                info.rotatie = int(abs(float(rot))) % 360 if rot is not None else 0
            except (TypeError, ValueError):
                info.rotatie = 0
        elif soort == "audio" and not info.heeft_audio:
            info.heeft_audio = True
            info.audio_codec = s.get("codec_name", "")
        elif soort == "data":
            info.data_sporen += 1

    return info


def frames_in(pad: Path) -> int:
    """Hoeveel videoframes staan er écht in een bestand.

    Telt ze, niet uit de header: `nb_frames` ontbreekt of liegt bij een
    stroom die met `-frames:v` is afgeknipt. Een bestand zonder videospoor
    (of zonder frames) geeft 0 terug in plaats van een fout — de aanroeper
    wil juist weten dát het er geen zijn.
    """
    try:
        r = _draai(
            [
                str(paths.ffprobe()), "-v", "error", "-select_streams", "v:0",
                "-count_frames", "-show_entries", "stream=nb_read_frames",
                "-of", "csv=p=0", str(pad),
            ],
            timeout=1800,
        )
    except MediaFout:
        return 0
    cijfers = "".join(c for c in (r.stdout or "") if c.isdigit())
    return int(cijfers) if cijfers else 0


def maak_proxy(
    bron: Path,
    doel: Path,
    *,
    hoogte: int = 540,
    fps: int = 30,
    overschrijf: bool = False,
) -> Path:
    """Maak een kleine h264-proxy voor analyse en preview.

    De proxy behoudt de beeldverhouding en past rotatie definitief toe, zodat
    latere analyse nooit meer over orientatie hoeft na te denken.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    if doel.exists() and not overschrijf and doel.stat().st_size > 0:
        return doel

    encoder, opties = video_encoder()
    tijdelijk = doel.with_suffix(".deel.mp4")
    cmd = [
        str(paths.ffmpeg()),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        # Hardware-decode waar beschikbaar (VideoToolbox / NVDEC / QSV / D3D11VA).
        # "auto" valt stil terug op software als het niet kan.
        "-hwaccel",
        "auto",
        "-i",
        str(bron),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        # Breedte op een veelvoud van 8, niet alleen even. Op de Intel-runner
        # (VideoToolbox op een paravirtuele GPU) gaf een breedte van 406 een
        # stroom die OpenCV als 405 breed las — met NaN als framerate en een
        # kapotte analyse als gevolg (03-10-2026). Encoders en decoders
        # houden van blokken; 8 kost hoogstens 4 pixels beeldverhouding.
        f"scale='trunc(iw*{hoogte}/ih/8+0.5)*8':{hoogte}:flags=fast_bilinear",
        "-r",
        str(fps),
        "-c:v",
        encoder,
        *opties,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(tijdelijk),
    ]
    _draai(cmd)
    tijdelijk.replace(doel)
    return doel


def haal_audio(bron: Path, doel: Path, *, sr: int = 16000, mono: bool = True) -> Path | None:
    """Trek audio uit een bestand als wav. Geeft None als er geen audio is."""
    doel.parent.mkdir(parents=True, exist_ok=True)
    if doel.exists() and doel.stat().st_size > 0:
        return doel
    try:
        _draai(
            [
                str(paths.ffmpeg()),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(bron),
                "-vn",
                "-map",
                "0:a:0",
                "-ac",
                "1" if mono else "2",
                "-ar",
                str(sr),
                "-c:a",
                "pcm_s16le",
                str(doel),
            ]
        )
    except MediaFout:
        return None
    return doel if doel.exists() else None


def stiltes(pad: Path, *, drempel_db: int = -32, minimale_duur: float = 0.35) -> list[tuple[float, float]]:
    """Vind stille stukken met ffmpeg silencedetect. Geeft (start, eind) in seconden."""
    r = subprocess.run(
        [
            str(paths.ffmpeg()),
            "-hide_banner",
            "-nostats",
            "-i",
            str(pad),
            "-af",
            f"silencedetect=noise={drempel_db}dB:d={minimale_duur}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    uit: list[tuple[float, float]] = []
    start: float | None = None
    for regel in (r.stderr or "").splitlines():
        if "silence_start:" in regel:
            try:
                start = float(regel.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                start = None
        elif "silence_end:" in regel and start is not None:
            try:
                eind = float(regel.split("silence_end:")[1].strip().split()[0])
                uit.append((start, eind))
            except (IndexError, ValueError):
                pass
            start = None
    return uit


def vind_bronnen(map_pad: Path, *, diep: bool = False) -> list[Path]:
    """Alle videobestanden in een map, alfabetisch. Verborgen bestanden overslaan.

    `diep=True` kijkt ook in onderliggende mappen. Dat is wat je wilt als
    iemand een SD-kaart of een hele cameramap in het venster sleept: daar
    staan de clips in `DCIM/100GOPRO/`, niet in de wortel. De projectmap
    `bronnen/` is plat, dus daar blijft `diep=False` goed.
    """
    if not map_pad.exists():
        return []
    kandidaten = map_pad.rglob("*") if diep else map_pad.iterdir()
    return sorted(
        p
        for p in kandidaten
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIES
        # Geen enkel deel van het pad mag verborgen zijn: .Trashes, .Spotlight-V100
        and not any(deel.startswith(".") for deel in p.relative_to(map_pad).parts)
    )


def vind_muziek(map_pad: Path) -> list[Path]:
    if not map_pad.exists():
        return []
    return sorted(
        p
        for p in map_pad.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIES and not p.name.startswith(".")
    )


def heeft_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def maak_thumbnail(bron: Path, doel: Path, *, breedte: int = 320, op: float = 0.0) -> Path:
    """Eén klein JPG uit een video, voor de clipkaarten in de app.

    Niet te verwarren met `studio.maak_thumbnails()`: dat maakt een strook van
    24 beelden voor de tijdlijn. Hier is één beeld genoeg, en dan liever breder.

    `op` is het moment in seconden. Een `-ss` vóór `-i` zoekt snel en hoeft
    niets weg te gooien; dat mag hier, want we knippen geen montage maar
    pakken één losse frame.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    if doel.exists() and doel.stat().st_size > 0:
        return doel
    tijdelijk = doel.with_suffix(".deel.jpg")
    _draai(
        [
            str(paths.ffmpeg()),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, op):.3f}",
            "-i",
            str(bron),
            "-frames:v",
            "1",
            "-vf",
            f"scale={breedte}:-2:flags=fast_bilinear",
            "-q:v",
            "4",
            str(tijdelijk),
        ],
        timeout=120,
    )
    tijdelijk.replace(doel)
    return doel
