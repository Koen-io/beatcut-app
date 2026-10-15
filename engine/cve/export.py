"""De uitvoer: de afgewerkte video wegschrijven zoals de gebruiker hem wil.

De render (`render.py`) maakt altijd hetzelfde: een H.264-MP4 op de maat van
het canvas. Dat is de *master*. Deze module zet die master om naar wat er in
het exportmenu gekozen is — ander formaat, andere codec, kleiner, andere
bitrate, ander geluid, andere map.

**Waarom een aparte stap en niet in de render zelf.** De render is op het
frame nauwkeurig (zie `projectgeheugen/render-ffmpeg.md`: framerooster,
`-frames:v`, staarten). Elke instelling die daar doorheen moet is een nieuwe
manier om een frame te verliezen. Hier gaat één af bestand in en één af
bestand uit; wat er mis kan gaan is te overzien.

**Wie niets verandert krijgt de master zelf.** De standaardkeuze is precies
wat de render maakt; dan wordt er niets omgezet (en dus niets slechter) en
hooguit gekopieerd naar de gekozen map.

**Er wordt nooit iets overschreven.** Bestaat de naam al, dan komt er `-2`
achter — dezelfde afspraak als bij terugzetten.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from . import editie, media, paths

# Wat er in welk bestandsformaat mag. MP4 is het formaat dat overal speelt en
# krijgt daarom alleen wat overal speelt; MOV en MKV kunnen de rest aan.
CONTAINERS: dict[str, dict] = {
    "mp4": {"label": "MP4", "uitleg": "Speelt overal: telefoon, tv, YouTube, Instagram.",
            "video": ["h264", "hevc"], "audio": ["aac", "geen"]},
    "mov": {"label": "MOV", "uitleg": "QuickTime. Voor Final Cut, Premiere en DaVinci Resolve.",
            "video": ["h264", "hevc", "prores"], "audio": ["aac", "alac", "pcm", "geen"]},
    "mkv": {"label": "MKV", "uitleg": "Matroska. Voor archief en mediaspelers als VLC en Plex.",
            "video": ["h264", "hevc", "prores"], "audio": ["aac", "flac", "pcm", "geen"]},
}
CODECS: dict[str, dict] = {
    "h264": {"label": "H.264", "uitleg": "Speelt op elk apparaat."},
    "hevc": {"label": "H.265 (HEVC)",
             "uitleg": "Zelfde kwaliteit in een kleiner bestand; oudere apparaten spelen het niet."},
    "prores": {"label": "Apple ProRes",
               "uitleg": "Voor verder bewerken. Bijna verliesvrij en erg groot."},
}
AUDIO: dict[str, dict] = {
    "aac": {"label": "AAC", "uitleg": "De standaard; speelt overal."},
    "alac": {"label": "Apple Lossless", "uitleg": "Verliesvrij, voor Apple-programma's."},
    "flac": {"label": "FLAC", "uitleg": "Verliesvrij."},
    "pcm": {"label": "PCM 24-bit", "uitleg": "Onbewerkt geluid, voor verder bewerken."},
    "geen": {"label": "Geen geluid", "uitleg": "Alleen beeld."},
}
# Bits per pixel per beeld. 0,15 is wat de render zelf gebruikt (1080p30 ≈
# 9 Mbit/s); HEVC haalt hetzelfde beeld uit ruwweg 60 % daarvan.
KWALITEIT: dict[str, dict] = {
    "klein": {"label": "Klein bestand", "bpp": 0.07},
    "standaard": {"label": "Standaard", "bpp": 0.15},
    "hoog": {"label": "Hoog", "bpp": 0.25},
    "eigen": {"label": "Eigen bitrate", "bpp": 0.15},
}
HEVC_FACTOR = 0.6
# ProRes heeft geen bitrate maar profielen. Mbit/s bij 1920x1080 op 29,97
# beelden, uit Apples eigen tabel (ProRes White Paper); schaalt mee met de
# pixels per seconde.
PRORES: dict[str, dict] = {
    "proxy": {"label": "Proxy", "nr": 0, "mbps": 45},
    "lt": {"label": "LT", "nr": 1, "mbps": 102},
    "standaard": {"label": "422", "nr": 2, "mbps": 147},
    "hq": {"label": "422 HQ", "nr": 3, "mbps": 220},
}
KORTE_ZIJDEN = [2160, 1440, 1080, 720, 540]
FPS = [24, 25, 30, 50, 60]
AUDIO_KBPS = [128, 192, 256, 320]
SAMPLERATES = [48000, 44100]
BITRATE_MIN, BITRATE_MAX = 1.0, 200.0  # Mbit/s, voor "eigen bitrate"

# Tekens die in een bestandsnaam op Windows niet mogen. Ook op de Mac weren:
# een export die je naar een Windows-pc of usb-stick kopieert moet daar openen.
_VERBODEN = '<>:"/\\|?*'


@dataclass
class Keuze:
    """Alles wat er in het exportmenu te kiezen valt. De standaard is de master."""

    container: str = "mp4"
    codec: str = "h264"
    #: "bron" of de korte zijde in pixels (1080 = 1080p, ook bij een staande video).
    resolutie: str = "bron"
    #: "bron" of beelden per seconde.
    fps: str = "bron"
    kwaliteit: str = "standaard"
    #: Mbit/s; telt alleen bij kwaliteit "eigen".
    bitrate: float = 12.0
    prores: str = "hq"
    audio: str = "aac"
    audio_kbps: int = 192
    samplerate: int = 48000
    #: Map waar het bestand komt; leeg = bij het project.
    map: str = ""
    #: Bestandsnaam zonder extensie; leeg = de projectnaam.
    naam: str = ""

    def is_master(self) -> bool:
        """Is dit precies wat de render al maakt? Dan valt er niets om te zetten."""
        return (
            self.container == "mp4" and self.codec == "h264"
            and self.resolutie == "bron" and self.fps == "bron"
            and self.kwaliteit == "standaard" and self.audio == "aac"
            and self.audio_kbps == 192 and self.samplerate == 48000
        )


def _keus(waarde, toegestaan, wat: str) -> str:
    s = str(waarde)
    if s not in toegestaan:
        raise ValueError(f"{wat} {s!r} kan niet. Kies uit: {', '.join(map(str, toegestaan))}.")
    return s


def lees_keuze(d: dict | None) -> Keuze:
    """Maak van wat de app stuurt een gecontroleerde keuze.

    Streng, zonder stil te repareren: een combinatie die niet kan (ProRes in
    MP4) is een fout in gewone woorden, geen export die iets anders wordt dan
    er op het scherm stond.
    """
    d = dict(d or {})
    k = Keuze()
    k.container = _keus(d.get("container", k.container), CONTAINERS, "Bestandsformaat")
    c = CONTAINERS[k.container]
    k.codec = _keus(d.get("codec", k.codec), CODECS, "Codec")
    if k.codec not in c["video"]:
        raise ValueError(
            f"{CODECS[k.codec]['label']} past niet in een {c['label']}-bestand. "
            f"Kies MOV of MKV, of een andere codec."
        )
    if k.codec not in beschikbare_codecs():
        raise ValueError(f"{CODECS[k.codec]['label']} kan deze computer niet maken.")
    k.resolutie = _keus(d.get("resolutie", "bron"), ["bron", *map(str, KORTE_ZIJDEN)], "Resolutie")
    k.fps = _keus(d.get("fps", "bron"), ["bron", *map(str, FPS)], "Beeldsnelheid")
    k.kwaliteit = _keus(d.get("kwaliteit", k.kwaliteit), KWALITEIT, "Kwaliteit")
    try:
        k.bitrate = float(d.get("bitrate", k.bitrate))
    except (TypeError, ValueError):
        raise ValueError("De bitrate moet een getal zijn, in Mbit/s.") from None
    if k.kwaliteit == "eigen" and not (BITRATE_MIN <= k.bitrate <= BITRATE_MAX):
        raise ValueError(
            f"Kies een bitrate tussen {BITRATE_MIN:g} en {BITRATE_MAX:g} Mbit/s."
        )
    k.prores = _keus(d.get("prores", k.prores), PRORES, "ProRes-profiel")
    k.audio = _keus(d.get("audio", k.audio), AUDIO, "Geluid")
    if k.audio not in c["audio"]:
        raise ValueError(
            f"{AUDIO[k.audio]['label']} past niet in een {c['label']}-bestand."
        )
    k.audio_kbps = int(_keus(d.get("audio_kbps", k.audio_kbps), list(map(str, AUDIO_KBPS)),
                             "Geluidskwaliteit"))
    k.samplerate = int(_keus(d.get("samplerate", k.samplerate), list(map(str, SAMPLERATES)),
                             "Samplefrequentie"))
    k.map = str(d.get("map") or "").strip()
    k.naam = veilige_naam(str(d.get("naam") or ""))
    return k


def veilige_naam(naam: str) -> str:
    """Een bestandsnaam die op macOS én Windows mag. Leeg blijft leeg."""
    schoon = "".join(" " if (t in _VERBODEN or ord(t) < 32) else t for t in naam)
    return " ".join(schoon.split()).strip(". ")[:120]


# -- wat kan deze computer -------------------------------------------------

_HEVC: list[tuple[str, list[str]]] = [
    ("hevc_videotoolbox", ["-b:v", "8M", "-allow_sw", "1"]),
    ("hevc_nvenc", ["-b:v", "8M"]),
    ("hevc_qsv", ["-b:v", "8M"]),
    ("hevc_amf", ["-b:v", "8M"]),
    ("hevc_mf", ["-b:v", "8M", "-hw_encoding", "1"]),
    ("hevc_mf", ["-b:v", "8M"]),
    ("libx265", ["-b:v", "8M"]),
]
_encoders: dict[str, tuple[str, list[str]] | None] = {}


def _encoder(codec: str) -> tuple[str, list[str]] | None:
    """De encoder voor deze codec die hier écht werkt, of `None`.

    Net als `media.video_encoder()`: in de lijst staan is niet genoeg, er moet
    een proefencode slagen. Eén keer per sessie; het antwoord verandert niet.
    """
    if codec in _encoders:
        return _encoders[codec]
    with _encoderslot:
        return _encoder_meten(codec)


def warm_op() -> threading.Thread:
    """Probeer de encoders alvast, in een eigen draad.

    De proefencodes kosten samen enkele seconden. Gebeuren ze pas bij het
    eerste `export.mogelijkheden`, dan staat de leeslus van de engine zolang
    stil en reageert de hele app niet — gezien bij het nalopen op 05-10-2026.
    `rpc.draai()` roept dit bij het opstarten; tegen de tijd dat iemand stap 5
    opent is het antwoord er al. Het slot zorgt dat een vraag die tóch eerder
    komt gewoon wacht in plaats van dubbel te meten.
    """
    draad = threading.Thread(target=beschikbare_codecs, name="export-encoders", daemon=True)
    draad.start()
    return draad


_encoderslot = threading.Lock()


def _encoder_meten(codec: str) -> tuple[str, list[str]] | None:
    if codec in _encoders:
        return _encoders[codec]
    gevonden: tuple[str, list[str]] | None = None
    if codec == "h264":
        gevonden = media.video_encoder()
    elif codec == "hevc":
        for naam, opties in _HEVC:
            if media.encoder_werkt(naam, opties):
                gevonden = (naam, list(opties))
                break
    elif codec == "prores":
        opties = ["-profile:v", "3", "-vendor", "apl0"]
        if media.encoder_werkt("prores_ks", opties, pix_fmt="yuv422p10le"):
            gevonden = ("prores_ks", opties)
    _encoders[codec] = gevonden
    return gevonden


def beschikbare_codecs() -> list[str]:
    return [c for c in CODECS if _encoder(c) is not None]


# De knoppen bovenaan het menu. Elke voorinstelling is een complete keuze
# (zonder map en naam); wat deze computer niet kan valt eruit.
VOORINSTELLINGEN: list[dict] = [
    {"id": "standaard", "label": "Standaard", "uitleg": "MP4 die overal speelt.",
     "keuze": {}},
    {"id": "youtube", "label": "YouTube", "uitleg": "Hoge bitrate, zodat YouTube iets te comprimeren heeft.",
     "keuze": {"kwaliteit": "hoog", "audio_kbps": 320}},
    {"id": "social", "label": "Instagram · TikTok", "uitleg": "1080p, 30 beelden, wat de apps zelf ook maken.",
     "keuze": {"resolutie": "1080", "fps": "30", "audio_kbps": 256}},
    {"id": "delen", "label": "Klein om te delen", "uitleg": "720p in H.265: past in een appje of mail.",
     "keuze": {"codec": "hevc", "resolutie": "720", "kwaliteit": "klein", "audio_kbps": 128}},
    {"id": "bewerken", "label": "Verder bewerken", "uitleg": "ProRes 422 HQ met onbewerkt geluid.",
     "keuze": {"container": "mov", "codec": "prores", "prores": "hq", "audio": "pcm"}},
]


def standaardmap(project: str) -> Path:
    """Waar een export komt als er geen map gekozen is."""
    return paths.project_dir(project) / "renders" / "export"


def canvas(project: str) -> tuple[int, int, float, float]:
    """Breedte, hoogte, beelden per seconde en duur van de montage.

    Zonder (leesbare) montage het standaardcanvas: het menu moet zichzelf
    kunnen tekenen, ook als `edl.json` er nog niet of half ligt.
    """
    from .edl import EDL

    pad = paths.project_dir(project) / "edl.json"
    if not pad.exists():
        return 1920, 1080, 30.0, 0.0
    try:
        edl = EDL.lees(pad)
    except (OSError, ValueError, KeyError, TypeError):
        return 1920, 1080, 30.0, 0.0
    return edl.canvas.breedte, edl.canvas.hoogte, float(edl.canvas.fps), float(edl.duur)


def maat(breedte: int, hoogte: int, resolutie: str) -> tuple[int, int]:
    """De uitvoermaat bij een korte zijde, met even getallen en dezelfde verhouding."""
    if resolutie == "bron":
        return breedte, hoogte
    kort = int(resolutie)
    f = kort / min(breedte, hoogte)
    even = lambda x: max(2, int(round(x * f / 2)) * 2)  # noqa: E731
    return even(breedte), even(hoogte)


def mogelijkheden(project: str | None = None) -> dict:
    """Alles wat het exportmenu nodig heeft om zichzelf te tekenen."""
    codecs = beschikbare_codecs()
    b, h, fps, duur = canvas(project) if project else (1920, 1080, 30.0, 0.0)
    kort = min(b, h)
    return {
        "containers": [
            {"id": i, **{k: v for k, v in c.items()},
             "video": [v for v in c["video"] if v in codecs]}
            for i, c in CONTAINERS.items()
        ],
        "codecs": [
            {"id": i, **c, "beschikbaar": i in codecs,
             "encoder": (_encoder(i) or ("", []))[0]}
            for i, c in CODECS.items()
        ],
        "audio": [{"id": i, **a} for i, a in AUDIO.items()],
        "kwaliteit": [{"id": i, "label": q["label"]} for i, q in KWALITEIT.items()],
        "prores": [{"id": i, "label": p["label"]} for i, p in PRORES.items()],
        "resoluties": [
            {"id": "bron", "label": f"Zoals de montage ({b}×{h})", "breedte": b, "hoogte": h,
             "opgeschaald": False},
            *[
                {"id": str(z), "label": {2160: "4K", 1440: "1440p", 1080: "1080p",
                                         720: "720p", 540: "540p"}[z],
                 "breedte": maat(b, h, str(z))[0], "hoogte": maat(b, h, str(z))[1],
                 "opgeschaald": z > kort}
                for z in KORTE_ZIJDEN if z != kort
            ],
        ],
        "fps": FPS,
        "audio_kbps": AUDIO_KBPS,
        "samplerates": SAMPLERATES,
        "bitrate": {"min": BITRATE_MIN, "max": BITRATE_MAX},
        "bron": {"breedte": b, "hoogte": h, "fps": fps, "duur": duur},
        "standaardmap": str(standaardmap(project)) if project else "",
        "voorinstellingen": [
            v for v in VOORINSTELLINGEN
            if v["keuze"].get("codec", "h264") in codecs
        ],
    }


# -- rekenen ---------------------------------------------------------------


def video_bps(k: Keuze, breedte: int, hoogte: int, fps: float) -> int:
    """Hoeveel bits per seconde het beeld krijgt bij deze keuze."""
    b, h = maat(breedte, hoogte, k.resolutie)
    f = fps if k.fps == "bron" else float(k.fps)
    if k.codec == "prores":
        return int(PRORES[k.prores]["mbps"] * 1_000_000 * (b * h * f) / (1920 * 1080 * 29.97))
    if k.kwaliteit == "eigen":
        return int(k.bitrate * 1_000_000)
    bps = b * h * f * KWALITEIT[k.kwaliteit]["bpp"]
    if k.codec == "hevc":
        bps *= HEVC_FACTOR
    # Onder de 1,5 Mbit/s wordt elke hardware-encoder blokkerig, wat het beeld ook is.
    return max(1_500_000, int(bps))


def audio_bps(k: Keuze) -> int:
    """Geschat: verliesvrij hangt af van de muziek, PCM is exact."""
    if k.audio == "geen":
        return 0
    if k.audio == "aac":
        return k.audio_kbps * 1000
    if k.audio == "pcm":
        return k.samplerate * 24 * 2
    return int(k.samplerate * 16 * 2 * 0.6)  # alac/flac: ruwweg 60 % van cd-kwaliteit


def doelpad(project: str, k: Keuze) -> Path:
    """Waar het bestand komt. Bestaat de naam al, dan komt er een volgnummer achter."""
    map_ = Path(k.map).expanduser() if k.map else standaardmap(project)
    naam = k.naam or veilige_naam(project) or "video"
    pad = map_ / f"{naam}.{k.container}"
    n = 2
    while pad.exists():
        pad = map_ / f"{naam}-{n}.{k.container}"
        n += 1
    return pad


def controleer_map(project: str, k: Keuze) -> Path:
    """Kan er in de gekozen map geschreven worden? Vóór de render vragen, niet erna."""
    map_ = Path(k.map).expanduser() if k.map else standaardmap(project)
    if not k.map:
        if k.is_master() and not k.naam:
            # Er komt geen apart bestand; de master staat al in `renders/`.
            return map_.parent
        map_.mkdir(parents=True, exist_ok=True)
    if not map_.is_dir():
        raise ValueError(f"De map {map_} bestaat niet (meer). Kies een andere map.")
    try:
        with tempfile.NamedTemporaryFile(dir=map_, prefix=".beatcut-", delete=True):
            pass
    except OSError:
        raise ValueError(
            f"In de map {map_} mag {editie.NAAM} niet schrijven. Kies een andere map."
        ) from None
    return map_


def schat(project: str, d: dict | None) -> dict:
    """Wat komt eruit: maat, bitrate, geschatte grootte en waar het komt."""
    k = lees_keuze(d)
    b, h, fps, duur = canvas(project)
    ub, uh = maat(b, h, k.resolutie)
    v, a = video_bps(k, b, h, fps), audio_bps(k)
    map_ = Path(k.map).expanduser() if k.map else standaardmap(project)
    vrij: int | None
    try:
        vrij = shutil.disk_usage(map_ if map_.is_dir() else map_.parent.parent).free
    except OSError:
        vrij = None
    bytes_ = int((v + a) * duur / 8)
    # Wie niets verandert krijgt de master zelf; die staat in `renders/`.
    alleen_master = k.is_master() and not k.map and not k.naam
    pad = (
        paths.project_dir(project) / "renders" / f"{project}-eind.mp4"
        if alleen_master else doelpad(project, k)
    )
    return {
        "breedte": ub, "hoogte": uh,
        "fps": fps if k.fps == "bron" else float(k.fps),
        "video_bps": v, "audio_bps": a, "duur": duur,
        "bytes": bytes_,
        "pad": str(pad),
        "map_bestaat": map_.is_dir() or not k.map,
        "vrij": vrij,
        "past": vrij is None or bytes_ * 1.1 < vrij,
        "omzetten": not k.is_master(),
        "keuze": asdict(k),
    }


# -- wegschrijven ----------------------------------------------------------

# Kwaliteitsopties van de gevonden encoder die we vervangen door een bitrate.
_KWALITEITSOPTIES = {"-b:v", "-cq", "-global_quality", "-crf", "-preset", "-rc",
                     "-qp_i", "-qp_p", "-quality", "-q:v", "-maxrate", "-bufsize"}


def _zonder_kwaliteit(opties: list[str]) -> list[str]:
    """Houd wat de encoder nodig heeft om te werken (`-allow_sw`, `-hw_encoding`)."""
    uit: list[str] = []
    i = 0
    while i < len(opties):
        if opties[i] in _KWALITEITSOPTIES:
            i += 2
            continue
        uit.append(opties[i])
        i += 1
    return uit


def _video_args(k: Keuze, bps: int) -> list[str]:
    gevonden = _encoder(k.codec)
    if gevonden is None:
        raise ValueError(f"{CODECS[k.codec]['label']} kan deze computer niet maken.")
    naam, opties = gevonden
    if k.codec == "prores":
        return ["-c:v", naam, "-profile:v", str(PRORES[k.prores]["nr"]),
                "-vendor", "apl0", "-pix_fmt", "yuv422p10le"]
    args = ["-c:v", naam, *_zonder_kwaliteit(opties), "-b:v", str(bps)]
    if "nvenc" in naam or "amf" in naam or naam.startswith("lib"):
        args += ["-maxrate", str(int(bps * 1.5)), "-bufsize", str(bps * 2)]
    if naam == "mpeg4":
        args = ["-c:v", naam, "-b:v", str(bps)]
    args += ["-pix_fmt", "yuv420p"]
    if k.codec == "hevc" and k.container in ("mp4", "mov"):
        # Zonder dit label herkennen QuickTime en iOS een HEVC-bestand niet.
        args += ["-tag:v", "hvc1"]
    return args


def _audio_args(k: Keuze, master: media.MediaInfo) -> list[str]:
    if k.audio == "geen" or not master.heeft_audio:
        return ["-an"]
    if k.audio == "aac":
        if master.audio_codec == "aac" and k.audio_kbps == 192 and k.samplerate == 48000:
            return ["-c:a", "copy"]  # zo maakt de render hem al
        return ["-c:a", "aac", "-b:a", f"{k.audio_kbps}k", "-ar", str(k.samplerate)]
    codec = {"alac": "alac", "flac": "flac", "pcm": "pcm_s24le"}[k.audio]
    return ["-c:a", codec, "-ar", str(k.samplerate)]


def beeld_blijft(k: Keuze, breedte: int, hoogte: int, fps: float) -> bool:
    """Kan het beeld van de master ongewijzigd mee? Dan wordt het gekopieerd.

    Eén functie voor `commando()` en voor `montage.maak_video`: die laatste
    rendert de master ruimer als er nog een codering achteraan komt, en moet
    dus precies hetzelfde antwoord krijgen als de omzetting zelf.
    """
    zelfde_maat = maat(breedte, hoogte, k.resolutie) == (breedte, hoogte)
    zelfde_fps = k.fps == "bron" or abs(float(k.fps) - fps) <= 0.01
    return zelfde_maat and zelfde_fps and k.codec == "h264" and k.kwaliteit == "standaard"


def commando(k: Keuze, master: media.MediaInfo, doel: Path) -> list[str]:
    """De ffmpeg-argumenten ná `ffmpeg` zelf. Los te testen zonder iets te draaien."""
    b, h = maat(master.breedte, master.hoogte, k.resolutie)
    filters: list[str] = []
    if (b, h) != (master.breedte, master.hoogte):
        filters.append(f"scale={b}:{h}:flags=lanczos")
    if k.fps != "bron" and abs(float(k.fps) - master.fps) > 0.01:
        filters.append(f"fps={k.fps}")
    kopie = master.codec == "h264" and beeld_blijft(
        k, master.breedte, master.hoogte, master.fps or 30.0
    )
    video = ["-c:v", "copy"] if kopie else _video_args(
        k, video_bps(k, master.breedte, master.hoogte, master.fps or 30.0)
    )
    return [
        "-i", str(master.pad), "-map", "0:v:0", "-map", "0:a:0?",
        *(["-vf", ",".join(filters)] if filters else []),
        *video, *_audio_args(k, master),
        *(["-movflags", "+faststart"] if k.container in ("mp4", "mov") else []),
        str(doel),
    ]


def schrijf(project: str, master_pad: Path, k: Keuze, voortgang=None) -> dict:
    """Zet de master om naar de keuze en geef terug waar het resultaat staat.

    `voortgang(gedaan, totaal)` in seconden video. Het bestand ontstaat onder
    een tijdelijke naam en krijgt zijn echte naam pas als het af is: een
    afgebroken export laat geen half bestand achter dat op een video lijkt.
    """
    controleer_map(project, k)
    if k.is_master() and not k.map and not k.naam:
        return {"pad": str(master_pad), "bytes": master_pad.stat().st_size,
                "omgezet": False, "keuze": asdict(k)}
    doel = doelpad(project, k)
    doel.parent.mkdir(parents=True, exist_ok=True)
    # Het procesnummer erin: twee BeatCuts die dezelfde naam wegschrijven
    # mogen elkaars halve bestand niet overschrijven.
    deel = doel.with_name(f".{doel.stem}.{os.getpid()}.bezig{doel.suffix}")
    try:
        if k.is_master():
            shutil.copy2(master_pad, deel)
        else:
            info = media.probe(master_pad)
            media.zet_om(commando(k, info, deel), duur=info.duur, voortgang=voortgang)
        # Omzetten kan minuten duren. Staat er intussen iets op de gekozen
        # naam, dan krijgt dit bestand het volgende nummer: nooit overschrijven.
        if doel.exists():
            doel = doelpad(project, k)
        os.replace(deel, doel)
    finally:
        deel.unlink(missing_ok=True)
    return {"pad": str(doel), "bytes": doel.stat().st_size,
            "omgezet": not k.is_master(), "keuze": asdict(k)}
