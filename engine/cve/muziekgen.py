"""Muziek genereren met ACE-Step 1.5, als apart proces.

Waarom apart: ACE-Step heeft torch, mlx en een eigen Python 3.12-venv van
1,3 GB. Zou de engine dat importeren, dan sleept elke `cve doctor` 13 GB
geheugen mee en moet de ingevroren app torch bundelen. Dus praten we met het
model zoals de app met ons praat: JSON per regel over stdin/stdout.

Waarom een server en niet een commando per track: het laden van het DiT-model
en het 1,7B-taalmodel kost 17 seconden (gemeten 03-10-2026,
`vendor/ace-step/VERSLAG.md` §2). Drie varianten zouden dan drie keer die 17
seconden kosten in plaats van één keer. Het proces blijft dus staan tussen
aanroepen.

Na het genereren is er altijd nabewerking nodig - dat is geen luxe:

- **De staart is stil.** Het bestand is precies zo lang als gevraagd, maar de
  muziek stopt 2 tot 7,5 seconden eerder. Zonder wegknippen loopt de montage
  aan het eind leeg (VERSLAG §4).
- **Afsluiten op een hele maat**, want het snijraster van BeatCut rekent in
  maten. Een track die midden in een maat ophoudt klinkt afgebroken.
- **Loudness naar de aanlevernorm**, met dezelfde twee-traps `loudnorm` als de
  renderer. ACE-Step levert tussen -12,6 en -16,7 LUFS af; dat is bruikbaar
  maar niet gelijk.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths

LICENTIE = "zelf gegenereerd met ACE-Step 1.5 (MIT), geen naamsvermelding nodig"
MODEL = "acestep-v15-turbo + acestep-5Hz-lm-1.7B"

# Welke motor het taalmodel draait. ACE-Step kent er drie
# (`acestep/llm_inference.py`): `mlx` alleen op Apple silicon, `vllm` alleen
# met CUDA, en `pt` (gewoon PyTorch) overal. Op Windows bestaat mlx niet en
# valt vllm buiten wat hun pyproject meelevert, dus daar is `pt` de keuze die
# werkt - met of zonder NVIDIA-kaart.
LM_BACKEND = "mlx" if sys.platform == "darwin" else "pt"

# Hoe lang het model mag doen over opstarten en over één track. Opstarten is
# gemeten op 17 s; de ruime marge is voor een koude schijf en voor het geval
# het taalmodel zich nog moet ophalen.
GEDULD_START = 600.0
GEDULD_TRACK = 900.0

# -50 dBFS: onder deze grens noemen we het stilte. Zelfde grens als in de
# meting van VERSLAG §4, zodat de getallen daar hier terugkomen.
STILTE_DBFS = -50.0
MAAT = 4  # 4/4; ACE-Step krijgt timesignature="4" mee

# Acht genres, zoals in het ontwerp (ontwerp/beatcut2/Main.dc.html, muziektab).
# Per genre een vaste beschrijving, een toonsoort en een standaardtempo. De
# beschrijving is wat ACE-Step werkelijk stuurt; de chip in de interface is
# alleen het label.
GENRES: dict[str, dict] = {
    "Pop": dict(
        bpm=118, keyscale="F major",
        beschrijving="Modern pop track, catchy melody, punchy drums, warm bass, "
                     "bright synth chords, polished radio production, confident and upbeat",
    ),
    "House": dict(
        bpm=124, keyscale="A minor",
        beschrijving="Energetic house track, four-on-the-floor kick, driving bassline, "
                     "bright plucked synth stabs, airy pads, crisp hi-hats, club-ready",
    ),
    "Electronic": dict(
        bpm=128, keyscale="D minor",
        beschrijving="Modern electronic track, crisp programmed drums, wide analog synths, "
                     "sidechained pads, clean low end, precise and forward-moving",
    ),
    "Hiphop": dict(
        bpm=92, keyscale="G minor",
        beschrijving="Hip hop instrumental, hard boom bap drums, deep sub bass, "
                     "sampled chords, vinyl texture, confident head-nod groove",
    ),
    "Lofi": dict(
        bpm=82, keyscale="C major",
        beschrijving="Lo-fi beat, dusty drums, soft electric piano, warm tape saturation, "
                     "mellow bass, relaxed and nostalgic",
    ),
    "Cinematic": dict(
        bpm=90, keyscale="C major",
        beschrijving="Cinematic score, warm sustained strings, soft piano motif, "
                     "subtle low drone, slow build, spacious and hopeful",
    ),
    "Indie": dict(
        bpm=112, keyscale="E major",
        beschrijving="Indie track, jangly electric guitars, live drum kit, melodic bass, "
                     "bright and open, sunny and unhurried",
    ),
    "Ambient": dict(
        bpm=70, keyscale="A major",
        beschrijving="Ambient piece, long evolving pads, soft bell textures, "
                     "deep slow swells, almost no percussion, calm and weightless",
    ),
}

# Welk tempo bij welke montagestijl past. Actie wil snel, landschap wil ruimte.
# Dit hoort in de engine en niet in de interface: de interface weet niet dat
# `luchtvaart` lange shots heeft.
BPM_PER_STIJL: dict[str, int] = {
    "actie": 140,
    "vlog": 112,
    "reis": 122,
    "landschap": 92,
    "luchtvaart": 84,
}
BPM_STANDAARD = 120


def bpm_voorstel(stijl: str | None, genre: str | None = None) -> int:
    """Het tempo dat bij deze stijl hoort, bijgetrokken naar het genre.

    De stijl bepaalt het bereik (actie hoger, landschap lager), het genre de
    richting: house op 84 BPM bestaat niet en ambient op 140 ook niet. Daarom
    het midden van de twee, en niet een van de twee alleen.
    """
    uit_stijl = BPM_PER_STIJL.get((stijl or "").strip().lower(), BPM_STANDAARD)
    g = GENRES.get(genre or "")
    if g is None:
        return uit_stijl
    return int(round((uit_stijl + g["bpm"]) / 2))


def status() -> dict:
    """Is het muziekmodel er, waar staat het, en hoe groot is het."""
    wortel = paths.muziekmodel()
    if wortel is None:
        return {
            "aanwezig": False,
            "pad": None,
            "bytes": 0,
            "model": MODEL,
            "licentie": LICENTIE,
            "genres": lijst_genres(),
            "uitleg": "Het muziekmodel (ongeveer 11 GB) is nog niet geïnstalleerd.",
        }
    return {
        "aanwezig": True,
        "pad": str(wortel),
        "bytes": _mapgrootte(wortel),
        "model": MODEL,
        "licentie": LICENTIE,
        "genres": lijst_genres(),
        "uitleg": "Muziek wordt op deze computer gemaakt. Niets gaat naar internet.",
    }


def lijst_genres() -> list[dict]:
    return [{"naam": n, "bpm": g["bpm"]} for n, g in GENRES.items()]


def _mapgrootte(d: Path) -> int:
    totaal = 0
    for p in d.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                totaal += p.stat().st_size
        except OSError:
            continue
    return totaal


# -- het serverproces ------------------------------------------------------

# Dit script draait in de venv van ACE-Step, niet in die van BeatCut. Het staat
# hier als tekst en wordt bij het starten naar een tijdelijk bestand geschreven:
# als het een `.py` in dit pakket was, zat het in de PyInstaller-bundel en niet
# meer op schijf, en dan kon de andere Python het niet starten.
_SERVER_SRC = r'''
import json, os, sys

WORTEL = sys.argv[1]
sys.path.insert(0, WORTEL)
for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(v, None)

def uit(d):
    sys.stdout.write(json.dumps(d) + "\n")
    sys.stdout.flush()

try:
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music
    from acestep.model_downloader import ensure_lm_model

    CHECKPOINTS = os.path.join(WORTEL, "checkpoints")
    LM = os.environ.get("BEATCUT_LM", "acestep-5Hz-lm-1.7B")

    dit = AceStepHandler()
    bericht, ok = dit.initialize_service(
        project_root=WORTEL, config_path="acestep-v15-turbo",
        device="auto", offload_to_cpu=False,
    )
    if not ok:
        raise RuntimeError("DiT init mislukt: %s" % bericht)
    ensure_lm_model(LM, checkpoints_dir=CHECKPOINTS)
    llm = LLMHandler()
    bericht, ok = llm.initialize(
        checkpoint_dir=CHECKPOINTS, lm_model_path=LM,
        backend=os.environ.get("ACESTEP_LM_BACKEND", "mlx"),
        device="auto", offload_to_cpu=False, dtype=None,
    )
    if not ok:
        raise RuntimeError("taalmodel init mislukt: %s" % bericht)
except Exception as e:
    uit({"gereed": False, "fout": str(e)})
    sys.exit(1)

uit({"gereed": True, "model": LM})

for regel in sys.stdin:
    regel = regel.strip()
    if not regel:
        continue
    try:
        v = json.loads(regel)
        if v.get("opdracht") == "stop":
            break
        params = GenerationParams(
            task_type="text2music", thinking=True,
            caption=v["caption"], lyrics=v["lyrics"],
            instrumental=bool(v["instrumentaal"]), bpm=int(v["bpm"]),
            keyscale=v["keyscale"], timesignature="4",
            vocal_language=v["taal"], duration=float(v["duur"]),
            inference_steps=8, guidance_scale=1.0, seed=int(v["seed"]),
        )
        r = generate_music(dit, llm, params=params,
                           config=GenerationConfig(batch_size=1, audio_format="wav"),
                           save_dir=v["map"])
        if not r.success:
            uit({"ok": False, "fout": r.status_message or "generatie mislukt"})
            continue
        paden = [a.get("path") for a in (r.audios or []) if a.get("path")]
        if not paden:
            uit({"ok": False, "fout": "generatie gaf geen bestand terug"})
            continue
        uit({"ok": True, "pad": paden[0]})
    except Exception as e:
        uit({"ok": False, "fout": "%s: %s" % (type(e).__name__, e)})
'''


def _leesdraad(stdout) -> "queue.Queue[str | None]":
    """Leest `stdout` leeg in een eigen draad en legt elke regel in een rij.

    `None` in de rij betekent: de pijp is dicht, het proces is weg.
    """
    rij: queue.Queue[str | None] = queue.Queue()

    def lezen() -> None:
        try:
            for regel in stdout:
                rij.put(regel)
        except (OSError, ValueError):
            pass
        rij.put(None)

    threading.Thread(target=lezen, name="muziekserver-lezer", daemon=True).start()
    return rij


class Server:
    """Eén lopend ACE-Step-proces. Blijft staan zodat het model geladen blijft."""

    def __init__(self, wortel: Path) -> None:
        self.wortel = wortel
        self._proc: subprocess.Popen | None = None
        self._script: Path | None = None
        self._rij: queue.Queue[str | None] | None = None
        # Herentreedbaar, want `vraag()` houdt het slot al vast als hij
        # `start()` aanroept. Eén slot voor allebei: anders kunnen twee
        # projecten tegelijk starten en leest de een het `gereed`-antwoord
        # van de ander als zijn trackantwoord.
        self._slot = threading.RLock()
        self.model = ""

    # -- starten ----------------------------------------------------------
    def _commando(self) -> list[str]:
        """Het commando dat het serverproces start.

        `BEATCUT_MUZIEKSERVER` wijst naar een eigen script. Dat is de enige
        manier om de hele keten te testen zonder 11 GB model: de test zet er
        een nep-server neer die hetzelfde protocol spreekt.
        """
        eigen = os.environ.get("BEATCUT_MUZIEKSERVER")
        if eigen:
            import sys as _sys

            return [_sys.executable, eigen, str(self.wortel)]
        py = paths.muziekmodel_python(self.wortel)
        if py is None:
            raise RuntimeError(f"Geen Python gevonden in {self.wortel / '.venv'}")
        fd, naam = tempfile.mkstemp(prefix="beatcut-muziekserver-", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_SERVER_SRC)
        self._script = Path(naam)
        return [str(py), naam, str(self.wortel)]

    def _omgeving(self) -> dict[str, str]:
        omg = dict(os.environ)
        # De downloadcache binnen de installatie houden, zoals VERSLAG §1.
        omg.setdefault("HF_HOME", str(self.wortel / "hf"))
        omg["TOKENIZERS_PARALLELISM"] = "false"
        omg.setdefault("ACESTEP_LM_BACKEND", LM_BACKEND)
        for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            omg.pop(v, None)
        return omg

    def _lees_regel(self, tot: float) -> dict:
        """Eén JSON-regel van het proces, met een deadline die echt afgaat.

        Niet rechtstreeks `readline()`: die is niet af te breken. Een model
        dat zwijgt hield daarmee de werkdraad én het slot voor altijd bezet,
        ook al stond er een deadline bij — gemeten 03-10-2026 met een stil
        subprocess. Een aparte leesdraad legt de regels in een wachtrij; die
        draad mag blijven hangen (hij is een daemon), de aanroeper komt vrij.
        """
        assert self._rij is not None and self._proc is not None
        while True:
            rest = tot - time.monotonic()
            if rest <= 0:
                raise TimeoutError("het muziekmodel antwoordde niet binnen de tijd")
            try:
                regel = self._rij.get(timeout=rest)
            except queue.Empty:
                raise TimeoutError("het muziekmodel antwoordde niet binnen de tijd") from None
            if regel is None:
                code = self._proc.poll()
                raise RuntimeError(f"het muziekmodel stopte (afsluitcode {code})")
            regel = regel.strip()
            if not regel or not regel.startswith("{"):
                continue
            try:
                return json.loads(regel)
            except json.JSONDecodeError:
                continue

    def start(self, melder=None) -> None:
        with self._slot:
            if self._proc is not None and self._proc.poll() is None:
                return
            if melder:
                melder("Muziekmodel laden…")
            self._proc = subprocess.Popen(
                self._commando(), cwd=str(self.wortel), env=self._omgeving(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            self._rij = _leesdraad(self._proc.stdout)
            try:
                antwoord = self._lees_regel(time.monotonic() + GEDULD_START)
            except TimeoutError:
                # Laten staan zou betekenen dat de volgende vraag het late
                # `gereed` als zijn trackantwoord leest.
                self.stop()
                raise
            if not antwoord.get("gereed"):
                self.stop()
                raise RuntimeError(
                    f"het muziekmodel kon niet starten: {antwoord.get('fout') or 'onbekende fout'}"
                )
            self.model = str(antwoord.get("model") or MODEL)

    def vraag(self, opdracht: dict) -> dict:
        """Eén track genereren. Serieel: het model kan er maar één tegelijk."""
        with self._slot:
            self.start()
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(json.dumps(opdracht) + "\n")
            self._proc.stdin.flush()
            try:
                antwoord = self._lees_regel(time.monotonic() + GEDULD_TRACK)
            except TimeoutError:
                self.stop()
                raise
        if not antwoord.get("ok"):
            raise RuntimeError(antwoord.get("fout") or "het muziekmodel gaf geen muziek terug")
        return antwoord

    def stop(self) -> None:
        proc, self._proc, self._rij = self._proc, None, None
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write('{"opdracht":"stop"}\n')
                    proc.stdin.flush()
                proc.wait(timeout=10)
            except (OSError, subprocess.SubprocessError, ValueError):
                proc.kill()
        if self._script is not None:
            self._script.unlink(missing_ok=True)
            self._script = None


_server: Server | None = None
_serverslot = threading.Lock()


def server() -> Server:
    """De lopende server, of een nieuwe als er nog geen is."""
    global _server
    with _serverslot:
        wortel = paths.muziekmodel()
        if wortel is None:
            raise ValueError(
                "Het muziekmodel is nog niet geïnstalleerd. Haal het op met "
                "installer/muziekmodel/installeer-mac.sh (ongeveer 11 GB)."
            )
        if _server is None or _server.wortel != wortel:
            if _server is not None:
                _server.stop()
            _server = Server(wortel)
        return _server


def stop_server() -> None:
    global _server
    with _serverslot:
        if _server is not None:
            _server.stop()
            _server = None


# -- nabewerking -----------------------------------------------------------


def muziekeinde(pad: Path, *, drempel_dbfs: float = STILTE_DBFS) -> tuple[float, float]:
    """(lengte van het bestand, waar de muziek echt ophoudt) in seconden.

    Vensters van 50 ms, RMS per venster. De laatste plek waar het boven de
    drempel komt is het einde van de muziek; alles daarna is de stille staart
    die ACE-Step er bij elke track aan plakt.
    """
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(pad), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    lengte = len(mono) / float(sr)
    venster = max(1, int(sr * 0.05))
    n = len(mono) // venster
    if n == 0:
        return lengte, lengte
    blokken = mono[: n * venster].reshape(n, venster)
    rms = np.sqrt((blokken.astype(np.float64) ** 2).mean(axis=1))
    luid = np.flatnonzero(rms > 10 ** (drempel_dbfs / 20.0))
    if luid.size == 0:
        return lengte, lengte
    return lengte, min(lengte, float((luid[-1] + 1) * venster) / sr)


def _gemeten_bpm(pad: Path) -> float | None:
    """Het tempo zoals librosa het in het resultaat terugvindt.

    Alleen ter informatie. Bij zachte, beatloze muziek is deze meting
    onbetrouwbaar — op de cinematic-proeftrack waren twee librosa-methodes
    12 BPM met zichzelf oneens (VERSLAG §3). Wat naar de montage gaat is de
    BPM die aan ACE-Step gevraagd is.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(str(pad), sr=22050, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return round(float(np.ravel(tempo)[0]), 2)
    except Exception:  # noqa: BLE001 — een mislukte meting mag de track niet kosten
        return None


# Hoeveel het gemeten tempo van het gevraagde mag afwijken voordat we het nog
# eens met een andere seed proberen. Gemeten 03-10-2026 op drie runs met
# dezelfde opdracht (House, 124 BPM): 129,2 — 124,0 — 99,4. ACE-Step haalt het
# gevraagde tempo dus niet betrouwbaar; opnieuw proberen wel.
BPM_MARGE = 3.0
#: Eén keer componeren plus hooguit twee nieuwe seeds. Elke poging kost 12-21 s.
BPM_POGINGEN = 3


def bpm_afwijking(gemeten: float | None, gevraagd: int) -> float | None:
    """Hoe ver zit het gemeten tempo van het gevraagde af?

    Een halve of dubbele tel is dezelfde muziek, geen fout tempo: 62 BPM onder
    een opdracht van 124 telt als raak.
    """
    if gemeten is None or gemeten <= 0:
        return None
    return round(min(abs(gemeten * f - gevraagd) for f in (0.5, 1.0, 2.0)), 2)


def nabewerk(bron: Path, doel: Path, *, bpm: int, maat: int = MAAT) -> dict:
    """Stille staart eraf, afsluiten op een hele maat, loudness op de norm.

    De fade-out valt binnen de laatste maat, niet erna: anders zou hij de
    maatgrens weer verschuiven en is het hele punt weg.
    """
    from . import media, render

    bestandsduur, einde = muziekeinde(bron)
    maatlengte = maat * 60.0 / float(bpm)
    maten = max(1, int(einde // maatlengte))
    knip = min(einde, maten * maatlengte)
    fade = min(0.4, knip / 4.0)

    stappen = [
        f"[0:a]atrim=start=0:end={knip:.4f},asetpts=N/SR/TB,"
        f"afade=t=out:st={max(0.0, knip - fade):.4f}:d={fade:.4f}[getrimd]"
    ]
    invoer = ["-i", str(bron)]
    stappen, uit = render._met_loudnorm(invoer, stappen, "[getrimd]")

    doel.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            *invoer, "-filter_complex", ";".join(stappen), "-map", uit,
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(doel),
        ],
        check=True, capture_output=True, timeout=900,
    )
    return {
        "duur": round(knip, 3),
        "maten": maten,
        "stilte_weg": round(bestandsduur - einde, 3),
        "fade": round(fade, 3),
        "lufs_doel": media.LUFS_DOEL,
        "true_peak_doel": media.TRUE_PEAK_DOEL,
    }


# -- genereren -------------------------------------------------------------


def _prompt(genre: str, stemming: str | None, bpm: int, zang: bool) -> str:
    g = GENRES[genre]
    stukken = [g["beschrijving"], f"{bpm} BPM"]
    if stemming:
        stukken.append(stemming.strip())
    stukken.append("with clear lead vocals" if zang else "Instrumental, no vocals")
    return ", ".join(stukken)


def map_voor(project: str) -> Path:
    d = paths.project_dir(project) / "muziek" / "gegenereerd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def genereer(
    project: str,
    *,
    genre: str = "House",
    stemming: str | None = None,
    bpm: int | None = None,
    duur: float = 30.0,
    zang: bool = False,
    varianten: int = 3,
    stijl: str | None = None,
    seed: int | None = None,
    melder=None,
) -> list[dict]:
    """Eén tot drie tracks maken, nabewerken en in het project zetten.

    Varianten verschillen alleen in de seed. Dezelfde prompt met een andere
    seed geeft een andere uitvoering van dezelfde opdracht — dat is precies
    waar de drie varianten voor zijn.

    `seed` vastzetten maakt het resultaat herhaalbaar; zonder is het de klok.
    Het model haalt het gevraagde tempo niet betrouwbaar, dus elke variant
    wordt na afloop gemeten en bij meer dan `BPM_MARGE` afwijking hooguit
    twee keer met een andere seed overgedaan. De dichtstbijzijnde wint.
    """
    if genre not in GENRES:
        raise ValueError(f"Onbekend genre: {genre}. Kies uit: {', '.join(GENRES)}")
    varianten = max(1, min(3, int(varianten)))
    duur = max(5.0, min(240.0, float(duur)))
    tempo = int(bpm) if bpm else bpm_voorstel(stijl, genre)
    prompt = _prompt(genre, stemming, tempo, zang)
    g = GENRES[genre]

    srv = server()
    if melder:
        melder(0, varianten, "Muziekmodel laden…")
    srv.start()

    doelmap = map_voor(project)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    basis_seed = int(seed) if seed is not None else int(time.time()) % 1_000_000
    with tempfile.TemporaryDirectory(prefix="beatcut-muziek-") as ruw:
        uit: list[dict] = []
        for i in range(varianten):
            letter = "ABC"[i]
            beste: tuple[Path, dict, float | None, float, int] | None = None
            for poging in range(BPM_POGINGEN):
                variantseed = basis_seed + i * 7919 + poging * 104729
                if melder:
                    melder(i, varianten, (
                        f"Variant {letter} componeren…" if poging == 0
                        else f"Variant {letter} opnieuw — het tempo klopte nog niet…"
                    ))
                antwoord = srv.vraag({
                    "caption": prompt,
                    "lyrics": "[Instrumental]" if not zang else "",
                    "instrumentaal": not zang,
                    "bpm": tempo,
                    "keyscale": g["keyscale"],
                    "taal": "en" if zang else "unknown",
                    "duur": duur,
                    "seed": variantseed,
                    "map": ruw,
                })
                rauw = Path(antwoord["pad"])
                # Nog niet in het project: een poging die afvalt hoort daar niet
                # te blijven liggen.
                tussen = Path(ruw) / f"klaar-{letter.lower()}-{poging}.wav"
                meting = nabewerk(rauw, tussen, bpm=tempo)
                gemeten = _gemeten_bpm(tussen)
                afw = bpm_afwijking(gemeten, tempo)
                if beste is None or afw is not None and afw < beste[3]:
                    beste = (tussen, meting, gemeten, 999.0 if afw is None else afw, variantseed)
                if afw is not None and afw <= BPM_MARGE:
                    break
            assert beste is not None  # BPM_POGINGEN is altijd >= 1
            tussen, meting, gemeten, afw, variantseed = beste
            naam = f"{genre.lower()}-{tempo}bpm-{stamp}-{letter.lower()}.wav"
            doel = doelmap / naam
            shutil.move(str(tussen), str(doel))
            info = {
                "variant": letter,
                "pad": str(doel),
                "bestand": naam,
                "genre": genre,
                "stemming": stemming or None,
                "zang": bool(zang),
                "bpm": tempo,
                "bpm_gemeten": gemeten,
                "bpm_afwijking": None if afw >= 999.0 else afw,
                "duur": meting["duur"],
                "gevraagde_duur": duur,
                "seed": variantseed,
                "prompt": prompt,
                "model": srv.model or MODEL,
                "licentie": LICENTIE,
                "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **{k: meting[k] for k in ("maten", "stilte_weg", "fade")},
            }
            doel.with_suffix(".json").write_text(
                json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            uit.append(info)
            if melder:
                melder(i + 1, varianten, f"Variant {letter} klaar")
    return uit


def bestaande(project: str) -> list[dict]:
    """Wat er eerder voor dit project gegenereerd is, nieuwste eerst."""
    d = paths.PROJECTEN / project / "muziek" / "gegenereerd"
    if not d.is_dir():
        return []
    uit = []
    for j in sorted(d.glob("*.json"), reverse=True):
        try:
            info = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if Path(info.get("pad", "")).exists():
            uit.append(info)
    return uit


_bezig: set[str] = set()
_bezigslot = threading.Lock()


def in_achtergrond(project: str, melder=None, **kw) -> bool:
    """Genereren in een werkdraad. `False` als er voor dit project al iets loopt.

    Niet in de leeslus: één track kost 12 tot 21 seconden en drie dus een
    minuut. Zolang zou de app op elk ander verzoek staan wachten.
    """
    with _bezigslot:
        if project in _bezig:
            return False
        _bezig.add(project)

    def voortgang(gedaan: int, totaal: int, tekst: str) -> None:
        if melder:
            melder("voortgang", {
                "werk": "muziekgen", "project": project, "stap": "componeren",
                "gedaan": gedaan, "totaal": totaal, "tekst": tekst,
                "percentage": round(100.0 * gedaan / max(1, totaal)),
            })

    def werk() -> None:
        try:
            varianten = genereer(project, melder=voortgang, **kw)
        except Exception as e:  # noqa: BLE001 — de app moet het horen, niet de stacktrace
            if melder:
                melder("fout", {"werk": "muziekgen", "project": project,
                                "fout": str(e), "soort": type(e).__name__})
            return
        finally:
            with _bezigslot:
                _bezig.discard(project)
        if melder:
            melder("klaar", {"werk": "muziekgen", "project": project,
                             "varianten": varianten})

    threading.Thread(target=werk, daemon=True).start()
    return True


def is_bezig(project: str) -> bool:
    with _bezigslot:
        return project in _bezig


def bezige_projecten() -> list[str]:
    """Voor welke projecten loopt er nu een generatie? Zie `rpc.bezig`."""
    with _bezigslot:
        return sorted(_bezig)
